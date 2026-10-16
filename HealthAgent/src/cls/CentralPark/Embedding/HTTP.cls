/// OpenAI-compatible /embeddings and Ollama /api/embed, executed inside IRIS.
Class CentralPark.Embedding.HTTP Extends %RegisteredObject
{
ClassMethod Embedding(text As %String, configuration As %String)
{
    set config={}.%FromJSON(configuration)
    set base=config.%Get("baseUrl")
    do ##class(%Net.URLParser).Parse(base,.url)
    if ('$listfind($listbuild("http","https"),$get(url("scheme"))))!($get(url("host"))="")!($get(url("query"))'="")!($get(url("fragment"))'="")!($get(url("username"))'="")!(base["@") throw ##class(%Exception.General).%New("Embedding base URL must be an http(s) API root without credentials, query or fragment")
    set req=##class(%Net.HttpRequest).%New()
    set req.Server=url("host"), req.Https=(url("scheme")="https")
    set req.Port=$get(url("port"),$select(req.Https:443,1:80))
    set req.SSLConfiguration=config.%Get("sslConfig")
    set req.Timeout=60, req.OpenTimeout=20, req.FollowRedirect=0
    set req.ContentType="application/json", req.ContentCharset="UTF-8"
    if config.%Get("apiKey")'="" set req.Authorization="Bearer "_config.%Get("apiKey")
    set body={}, body.model=config.%Get("modelName"), body.input=text
    set endpoint=$zstrip($get(url("path")),">","/")
    if config.%Get("provider")="ollama" {
        set endpoint=endpoint_"/api/embed"
        do body.%Set("truncate",0,"boolean")
    } else {
        set endpoint=endpoint_"/embeddings", body."encoding_format"="float"
        if config.%Get("sendDimensions") set body.dimensions=config.%Get("dimensions")
    }
    do req.EntityBody.Write(body.%ToJSON())
    set sc=req.Post(endpoint)
    if 'sc throw ##class(%Exception.General).%New("Embedding endpoint request failed")
    if req.HttpResponse.StatusCode'=200 throw ##class(%Exception.General).%New("Embedding endpoint returned HTTP "_req.HttpResponse.StatusCode)
    set response={}.%FromJSON(req.HttpResponse.Data)
    if config.%Get("provider")="ollama" {
        set rows=response.%Get("embeddings")
        if '$isobject(rows) throw ##class(%Exception.General).%New("Missing embedding response")
        if 'rows.%IsA("%DynamicArray") throw ##class(%Exception.General).%New("Expected embedding response array")
        if rows.%Size()'=1 throw ##class(%Exception.General).%New("Expected one embedding")
        set embedding=rows.%Get(0)
    } else {
        set rows=response.%Get("data")
        if '$isobject(rows) throw ##class(%Exception.General).%New("Missing embedding response")
        if 'rows.%IsA("%DynamicArray") throw ##class(%Exception.General).%New("Expected embedding response array")
        if rows.%Size()'=1 throw ##class(%Exception.General).%New("Expected one embedding")
        set row=rows.%Get(0)
        if '$isobject(row) throw ##class(%Exception.General).%New("Invalid embedding response")
        if (row.%GetTypeOf("index")'="number")!(row.%Get("index")'=0) throw ##class(%Exception.General).%New("Unexpected embedding index")
        set embedding=row.%Get("embedding")
    }
    if '$isobject(embedding) throw ##class(%Exception.General).%New("Expected numeric embedding array")
    if 'embedding.%IsA("%DynamicArray") throw ##class(%Exception.General).%New("Expected numeric embedding array")
    if embedding.%Size()'=config.%Get("dimensions") throw ##class(%Exception.General).%New("Embedding dimension mismatch; check CP_EMBEDDING_DIMENSIONS and model output")
    for i=0:1:embedding.%Size()-1 {
        if embedding.%GetTypeOf(i)'="number" throw ##class(%Exception.General).%New("Embedding contains a non-numeric value")
        set $vector(vec,i+1,"xf32")=embedding.%Get(i)
    }
    quit vec
}
}
