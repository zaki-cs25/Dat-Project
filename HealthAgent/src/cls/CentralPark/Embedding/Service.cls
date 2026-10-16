/// Shared embedding configuration for both evidence collections.
Class CentralPark.Embedding.Service Extends %RegisteredObject
{
ClassMethod Config()
{
    set config=##class(%Embedding.Config).%OpenId("central-park-openai")
    if '$isobject(config) throw ##class(%Exception.General).%New("Embedding configuration missing")
    if config.VectorLength<1 throw ##class(%Exception.General).%New("Embedding dimensions must be positive")
    quit config
}

/// Credentials are deliberately excluded: rotating a key does not require reindexing.
ClassMethod Profile(config) As %String
{
    set data={}.%FromJSON(config.Configuration)
    set identity=$listbuild(config.EmbeddingClass,data.%Get("provider"),data.%Get("modelName"),data.%Get("baseUrl"),config.VectorLength,data.%Get("sendDimensions"),data.%Get("revision"))
    quit $system.Encryption.Base64Encode($system.Encryption.SHAHash(256,identity))
}

ClassMethod Embed(text As %String, config = "")
{
    if '$isobject(config) set config=..Config()
    set vec=$classmethod(config.EmbeddingClass,"Embedding",text,config.Configuration)
    if ($vectorop("length",vec)'=config.VectorLength)!($vectorop("count",vec)'=config.VectorLength) throw ##class(%Exception.General).%New("Embedding dimension mismatch; check CP_EMBEDDING_DIMENSIONS and model output")
    set nonzero=0
    for i=1:1:config.VectorLength { if $vector(vec,i)'=0 set nonzero=1 }
    if 'nonzero throw ##class(%Exception.General).%New("Embedding model returned a zero vector")
    quit vec
}
}
