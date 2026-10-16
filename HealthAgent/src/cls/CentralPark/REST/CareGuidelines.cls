/// Authenticated internal curated corpus import and condition-scoped search.
Class CentralPark.REST.CareGuidelines Extends %RegisteredObject
{
ClassMethod Embed(text As %String, config = "")
{
    quit ##class(CentralPark.Embedding.Service).Embed(text,config)
}

ClassMethod Import() As %Status
{
    set %response.ContentType = "application/json"
    try {
        set body = {}.%FromJSON(%request.Content)
        set document = body.%Get("document_id"), version = body.%Get("version_id")
        set passages = body.%Get("passages")
        if (document="")!(version="")!('$isobject(passages)) throw ##class(%Exception.General).%New("Missing document, version or passages")
        set documents=$listbuild("icmr-md-volume-1","icmr-md-volume-2","icmr-md-volume-3","icmr-md-volume-4","icmr-md-hypertension")
        set filenames=$listbuild("stw_manual_v1_stw_i.md","stw_v2.md","stw_v3.md","stw_v4.md","hypertension.md")
        set sourceIndex=$listfind(documents,document)
        if 'sourceIndex throw ##class(%Exception.General).%New("Only the five configured Markdown care documents can be imported")
        if passages.%Size()=0 throw ##class(%Exception.General).%New("No passages")
        set config=##class(CentralPark.Embedding.Service).Config()
        set profile=##class(CentralPark.Embedding.Service).Profile(config)
        // Embedding completes before any change to the active version pointer.
        for i=0:1:passages.%Size()-1 {
            set p = passages.%Get(i)
            if (p.%Get("reviewed")'=1)!(p.%Get("document_id")'=document)!(p.%Get("version_id")'=version) throw ##class(%Exception.General).%New("Unreviewed or mismatched passage")
            if p.%Get("review_policy")="showcase-bulk" {
                if (p.%Get("evidence_role")'="context")!('$listfind($listbuild("include","supporting-context","needs-review"),p.%Get("original_decision"))) throw ##class(%Exception.General).%New("Bulk import accepts non-rejected context only")
                set approval=p.%Get("bulk_approval")
                if '$isobject(approval) throw ##class(%Exception.General).%New("Missing showcase approval")
                if (approval.%Get("actor")="")!(approval.%Get("approved_at")="")!(approval.%Get("scope")'="non-rejected-context")!(approval.%Get("clinical_validation_complete",1)'=0)!(p.%Get("clinical_validation_complete",1)'=0) throw ##class(%Exception.General).%New("Showcase approval must not claim clinical validation")
            }
            set condition = p.%Get("condition")
            // The reviewed Python workflow catalogue supplies condition mappings.
            // Tags are extensible; validate their shape rather than eight names.
            if ($length(condition)<1)!($length(condition)>64)!($extract(condition,1)'?1L)!($translate(condition,"abcdefghijklmnopqrstuvwxyz0123456789-")'="") throw ##class(%Exception.General).%New("Invalid condition tag")
            if (p.%Get("passage_id")="")!(p.%Get("text")="")!(p.%Get("section")="")!(p.%Get("original_text")="")!(p.%Get("applicability")="")!(p.%Get("reviewer")="") throw ##class(%Exception.General).%New("Incomplete reviewed passage")
            if p.%Get("source_format")'="markdown" throw ##class(%Exception.General).%New("Only Markdown care passages can be imported")
            if p.%Get("source_file")'=$list(filenames,sourceIndex) throw ##class(%Exception.General).%New("Markdown filename does not match the configured document")
            if (p.%Get("line_start")<1)!(p.%Get("line_end")<p.%Get("line_start")) throw ##class(%Exception.General).%New("Missing Markdown source line reference")
            if p.%Get("page")'="" throw ##class(%Exception.General).%New("Markdown passages must use source lines, not PDF pages")
            if $data(seen(p.%Get("passage_id"))) throw ##class(%Exception.General).%New("Duplicate passage ID")
            set seen(p.%Get("passage_id"))=1
            if ($length(p.%ToJSON())>32000)!($length(p.%Get("text"))>16000) throw ##class(%Exception.General).%New("Passage too large; preserve complete recommendation in a smaller reviewed passage")
            set rs = ##class(%SQL.Statement).%ExecDirect(,"SELECT Metadata, EmbeddingProfile FROM CentralPark_Data.CarePassage WHERE PassageID=?",p.%Get("passage_id"))
            if rs.%SQLCODE<0 throw ##class(%Exception.General).%New(rs.%Message)
            if rs.%Next() {
                if rs.Metadata'=p.%ToJSON() throw ##class(%Exception.General).%New("Passage IDs are immutable; use a new review revision")
                set existing(i)=1
                if rs.EmbeddingProfile=profile continue
            }
            set vectors(i)=..Embed(p.%Get("text")_" Applicability: "_p.%Get("applicability")_" Exceptions: "_p.%Get("exceptions"),config)
        }
        tstart
        // Serialize activation for this document; never remove old versions.
        lock +^CentralPark.CareImport(document):30
        if '$test throw ##class(%Exception.General).%New("Document import lock timed out")
        for i=0:1:passages.%Size()-1 {
            if '$data(existing(i)) {
                set p=passages.%Get(i)
                set rs=##class(%SQL.Statement).%ExecDirect(,"INSERT INTO CentralPark_Data.CarePassage (PassageID,DocumentID,VersionID,ConditionTag,Reviewed,Text,Metadata,Embedding,EmbeddingProfile) VALUES (?,?,?,?,?,?,?,?,?)",p.%Get("passage_id"),document,version,p.%Get("condition"),1,p.%Get("text"),p.%ToJSON(),vectors(i),profile)
                if rs.%SQLCODE<0 throw ##class(%Exception.General).%New(rs.%Message)
            } elseif $data(vectors(i)) {
                set p=passages.%Get(i)
                set rs=##class(%SQL.Statement).%ExecDirect(,"UPDATE CentralPark_Data.CarePassage SET Embedding=?,EmbeddingProfile=? WHERE PassageID=?",vectors(i),profile,p.%Get("passage_id"))
                if rs.%SQLCODE<0 throw ##class(%Exception.General).%New(rs.%Message)
            }
        }
        set rs=##class(%SQL.Statement).%ExecDirect(,"UPDATE CentralPark_Data.CareDocument SET ActiveVersion=? WHERE DocumentID=?",version,document)
        if rs.%SQLCODE<0 throw ##class(%Exception.General).%New(rs.%Message)
        if rs.%ROWCOUNT=0 {
            set rs=##class(%SQL.Statement).%ExecDirect(,"INSERT INTO CentralPark_Data.CareDocument (DocumentID,ActiveVersion) VALUES (?,?)",document,version)
            if rs.%SQLCODE<0 throw ##class(%Exception.General).%New(rs.%Message)
        }
        tcommit
        lock -^CentralPark.CareImport(document)
        set out={"status":"indexed"}
        set out."document_id"=document, out."version_id"=version, out.passages=passages.%Size()
        write out.%ToJSON()
    } catch ex {
        if $tlevel trollback
        if $get(document)'="" lock -^CentralPark.CareImport(document)
        set %response.Status="400 Bad Request"
        set out={}, out.error=ex.DisplayString()
        write out.%ToJSON()
    }
    quit $$$OK
}

ClassMethod Search() As %Status
{
    set %response.ContentType="application/json"
    try {
        set body={}.%FromJSON(%request.Content)
        set condition=body.%Get("condition"), query=body.%Get("query")
        set k=+body.%Get("k")
        if (k<1)!(k>5) set k=5
        if (condition="")!(query="") throw ##class(%Exception.General).%New("Condition and query required")
        // The application uses only the user's five Markdown sources. Archived
        // PDF rows remain available to saved citations but cannot enter new drafts.
        set library=body.%Get("library")
        if (library'="markdown")&&(library'="") {
            throw ##class(%Exception.General).%New("Unknown care evidence library")
        }
        // Omitting library uses the same restriction; there is no legacy fallback.
        set scope=" AND p.DocumentID IN ('icmr-md-volume-1','icmr-md-volume-2','icmr-md-volume-3','icmr-md-volume-4','icmr-md-hypertension')"
        // Empty active collection is an evidence absence, not an embedding failure.
        set available=##class(%SQL.Statement).%ExecDirect(,"SELECT COUNT(*) AS N FROM CentralPark_Data.CarePassage p JOIN CentralPark_Data.CareDocument d ON p.DocumentID=d.DocumentID AND p.VersionID=d.ActiveVersion WHERE p.ConditionTag=? AND p.Reviewed=1"_scope,condition)
        if available.%SQLCODE<0 throw ##class(%Exception.General).%New(available.%Message)
        do available.%Next()
        if available.N=0 {
            write "{""hits"":[]}"
            return $$$OK
        }
        set config=##class(CentralPark.Embedding.Service).Config()
        set profile=##class(CentralPark.Embedding.Service).Profile(config)
        set current=##class(%SQL.Statement).%ExecDirect(,"SELECT COUNT(*) AS N FROM CentralPark_Data.CarePassage p JOIN CentralPark_Data.CareDocument d ON p.DocumentID=d.DocumentID AND p.VersionID=d.ActiveVersion WHERE p.ConditionTag=? AND p.Reviewed=1 AND p.EmbeddingProfile=?"_scope,condition,profile)
        if current.%SQLCODE<0 throw ##class(%Exception.General).%New(current.%Message)
        do current.%Next()
        if current.N'=available.N throw ##class(%Exception.General).%New("Embedding model changed; republish reviewed care documents to reindex before searching")
        set vec=..Embed(query,config)
        // IRIS requires a declared length for cosine expressions. Stored vectors
        // already have this exact validated size; TO_VECTOR never changes their values.
        set sql="SELECT TOP ? p.Metadata, VECTOR_COSINE(TO_VECTOR(p.Embedding,float,"_(+config.VectorLength)_"), ?) AS Score FROM CentralPark_Data.CarePassage p JOIN CentralPark_Data.CareDocument d ON p.DocumentID=d.DocumentID AND p.VersionID=d.ActiveVersion WHERE p.ConditionTag=? AND p.Reviewed=1 AND p.EmbeddingProfile=?"_scope_" ORDER BY Score DESC"
        set rs=##class(%SQL.Statement).%ExecDirect(,sql,k,vec,condition,profile)
        if rs.%SQLCODE<0 throw ##class(%Exception.General).%New(rs.%Message)
        set hits=[]
        while rs.%Next() {
            set row={}.%FromJSON(rs.Metadata), row.score=rs.Score
            do hits.%Push(row)
        }
        set out={}, out.hits=hits
        write out.%ToJSON()
    } catch ex {
        set %response.Status="503 Service Unavailable"
        set out={}, out.error=ex.DisplayString()
        write out.%ToJSON()
    }
    quit $$$OK
}
}
