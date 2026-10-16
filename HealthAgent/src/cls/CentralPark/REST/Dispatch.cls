/// REST surface for Central Park.
///
/// Mounted at /centralpark by iris.script (and again by module.xml when
/// installed via IPM). Routes:
///
///   GET  /centralpark/health         liveness probe
///   POST /centralpark/care-guidelines/import reviewed, versioned care evidence
///   POST /centralpark/care-guidelines/search active care evidence by condition
///   POST /centralpark/vector/search original interview guideline retrieval
Class CentralPark.REST.Dispatch Extends %CSP.REST
{

Parameter HandleCorsRequest = 1;

Parameter CONTENTTYPE = "application/json";

/// Decode JSON request bytes before passing the stream to %FromJSON.
Parameter CONVERTINPUTSTREAM = 1;

Parameter CHARSET = "utf-8";

XData UrlMap [ XMLNamespace = "http://www.intersystems.com/urlmap" ]
{
<Routes>
  <Route Url="/health"                    Method="GET"  Call="GetHealth"/>
  <Route Url="/care-guidelines/import"    Method="POST" Call="PostCareImport"/>
  <Route Url="/care-guidelines/search"    Method="POST" Call="PostCareSearch"/>
  <Route Url="/vector/seed"               Method="POST" Call="PostVectorSeed"/>
  <Route Url="/vector/search"             Method="POST" Call="PostVectorSearch"/>
  <Route Url="/install/embedding-config"  Method="POST" Call="PostInstallEmbeddingConfig"/>

</Routes>
}

ClassMethod GetHealth() As %Status
{
    set %response.ContentType = "application/json"
    write "{""status"":""ok"",""service"":""central-park""}"
    quit $$$OK
}

ClassMethod PostCareImport() As %Status
{
    quit ##class(CentralPark.REST.CareGuidelines).Import()
}

ClassMethod PostCareSearch() As %Status
{
    quit ##class(CentralPark.REST.CareGuidelines).Search()
}

/// Refresh the shared embedding configuration from the IRIS environment.
ClassMethod PostInstallEmbeddingConfig() As %Status
{
    set %response.ContentType = "application/json"
    set sc = ##class(CentralPark.Install).InstallEmbeddingConfig()
    set hasKey = (($system.Util.GetEnviron("CP_EMBEDDING_API_KEY") '= "")!($system.Util.GetEnviron("OPENAI_API_KEY") '= ""))
    set out = {}
    set out.ok = $$$ISOK(sc)
    set out."hasKey" = hasKey
    if 'sc {
        set %response.Status="400 Bad Request"
        set out.error = $system.Status.GetErrorText(sc)
    } else {
        set config=##class(CentralPark.Embedding.Service).Config()
        set details={}.%FromJSON(config.Configuration)
        set out.model=details.%Get("modelName"),out.dimensions=config.VectorLength
        set out.profile=##class(CentralPark.Embedding.Service).Profile(config)
    }
    write out.%ToJSON()
    quit $$$OK
}

/// Upsert guideline rows. Body is a JSON array of { "slug", "source", "snippet" }.
/// IRIS embeds each snippet via the configured provider using the named
/// "central-park-openai" %Embedding.Config row, then inserts or updates.
/// Existing rows with the same slug are updated, new ones inserted.
ClassMethod PostVectorSeed() As %Status
{
    set %response.ContentType = "application/json"
    set tArr = [].%FromJSON(%request.Content)
    set inserted = 0, updated = 0, errors = 0
    set config=##class(CentralPark.Embedding.Service).Config()
    set profile=##class(CentralPark.Embedding.Service).Profile(config)
    set iter = tArr.%GetIterator()
    while iter.%GetNext(.key, .row) {
        set slug = row.%Get("slug")
        set source = row.%Get("source")
        set snippet = row.%Get("snippet")
        try {
            set vec = ##class(CentralPark.Embedding.Service).Embed(snippet,config)
        } catch ex {
            set errors = errors + 1
            continue
        }
        // Try update first, fall back to insert. The vector binds directly
        // (no TO_VECTOR string round-trip needed when passing a %Vector).
        set rs = ##class(%SQL.Statement).%ExecDirect(,
            "UPDATE CentralPark_Data.Guideline SET Source=?, Snippet=?, Embedding=?,EmbeddingProfile=? WHERE Slug=?",
            source, snippet, vec, profile, slug)
        if rs.%SQLCODE<0 { set errors=errors+1 continue }
        if rs.%ROWCOUNT > 0 {
            set updated = updated + 1
        } else {
            set rs = ##class(%SQL.Statement).%ExecDirect(,
                "INSERT INTO CentralPark_Data.Guideline (Slug, Source, Snippet, Embedding,EmbeddingProfile) VALUES (?, ?, ?, ?, ?)",
                slug, source, snippet, vec, profile)
            if rs.%SQLCODE = 0 set inserted = inserted + 1
            if rs.%SQLCODE < 0 set errors = errors + 1
        }
    }
    set out = {}
    set out.inserted = inserted
    set out.updated = updated
    set out.errors = errors
    write out.%ToJSON()
    quit $$$OK
}

/// Top-k cosine search over the guideline corpus. Body is
/// { "query": "<text>", "k": int }.
/// IRIS embeds the query with the same model as the documents, then runs cosine.
/// Response is { "hits": [{slug, source, snippet, score}, ...] }.
ClassMethod PostVectorSearch() As %Status
{
    set %response.ContentType = "application/json"
    set tBody = {}.%FromJSON(%request.Content)
    set query = tBody.%Get("query")
    set k = +$select(tBody.%Get("k")="": 5, 1: tBody.%Get("k"))
    try {
        set config=##class(CentralPark.Embedding.Service).Config()
        set profile=##class(CentralPark.Embedding.Service).Profile(config)
        set stale=##class(%SQL.Statement).%ExecDirect(,"SELECT COUNT(*) AS N FROM CentralPark_Data.Guideline WHERE EmbeddingProfile IS NULL OR EmbeddingProfile<>?",profile)
        if stale.%SQLCODE<0 throw ##class(%Exception.General).%New(stale.%Message)
        do stale.%Next()
        if stale.N>0 throw ##class(%Exception.General).%New("Embedding model changed; reseed interview guidelines before searching")
        set queryVec = ##class(CentralPark.Embedding.Service).Embed(query,config)
    } catch ex {
        set %response.Status = ..#HTTP500INTERNALSERVERERROR
        write "{""error"":""embedding_failed"",""detail"":"_$$$quote(ex.DisplayString())_"}"
        return $$$OK
    }
    set sql = "SELECT TOP ? Slug, Source, Snippet, VECTOR_COSINE(TO_VECTOR(Embedding,float,"_(+config.VectorLength)_"), ?) AS Score FROM CentralPark_Data.Guideline WHERE EmbeddingProfile=? ORDER BY Score DESC"
    set rs = ##class(%SQL.Statement).%ExecDirect(, sql, k, queryVec,profile)
    if rs.%SQLCODE<0 {
        set %response.Status="503 Service Unavailable"
        write "{""error"":""vector_search_failed""}"
        return $$$OK
    }
    set hits = []
    while rs.%Next() {
        set row = {}
        set row.slug = rs.Slug
        set row.source = rs.Source
        set row.snippet = rs.Snippet
        set row.score = rs.Score
        do hits.%Push(row)
    }
    set out = {}
    set out.hits = hits
    write out.%ToJSON()
    quit $$$OK
}

}
