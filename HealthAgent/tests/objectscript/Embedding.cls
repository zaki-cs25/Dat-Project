/// Synthetic cosine vectors for isolated integration tests ONLY.
/// Loaded manually into the test database; never copied to production images.
Class CareTest.Embedding Extends %RegisteredObject
{
ClassMethod Embedding(text As %String, config As %String)
{
    if text["FORCE_EMBEDDING_FAILURE" throw ##class(%Exception.General).%New("Synthetic embedding failure")
    set values="[1"
    for i=2:1:1536 set values=values_",0"
    set values=values_"]"
    set result=##class(%SQL.Statement).%ExecDirect(,"SELECT TO_VECTOR(?, float) AS V",values)
    if result.%SQLCODE<0 throw ##class(%Exception.General).%New(result.%Message)
    do result.%Next()
    quit result.V
}
}
