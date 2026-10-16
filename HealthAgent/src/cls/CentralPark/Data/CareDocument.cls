/// Active version pointer, switched only after all reviewed passages are indexed.
Class CentralPark.Data.CareDocument Extends %Persistent
{
Property DocumentID As %String(MAXLEN = 128) [ Required ];
Property ActiveVersion As %String(MAXLEN = 128);
Index DocumentIdx On DocumentID [ Unique ];
}
