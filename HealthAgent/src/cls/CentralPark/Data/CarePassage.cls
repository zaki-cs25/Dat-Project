/// Care-planning evidence. Completely separate from interview Guideline rows.
/// Old versions are retained because persisted drafts cite their passage IDs.
Class CentralPark.Data.CarePassage Extends %Persistent
{
Property PassageID As %String(MAXLEN = 256) [ Required ];
Property DocumentID As %String(MAXLEN = 128) [ Required ];
Property VersionID As %String(MAXLEN = 128) [ Required ];
Property ConditionTag As %String(MAXLEN = 64) [ Required ];
Property Reviewed As %Boolean;
Property Text As %String(MAXLEN = 16000);
Property Metadata As %String(MAXLEN = 32000);
/// Length is validated by Embedding.Service; model identity isolates vector spaces.
Property Embedding As %Vector(DATATYPE = "float");
Property EmbeddingProfile As %String(MAXLEN = 64);
Index PassageIdx On PassageID [ Unique ];
Index ConditionIdx On ConditionTag;
Index VersionIdx On (DocumentID, VersionID);
}
