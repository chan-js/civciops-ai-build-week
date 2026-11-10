// Create a text parameter named ExportFolder, pointing to the Python output folder.
let
    Source = Csv.Document(File.Contents(ExportFolder & "/community_plan.csv"),[Delimiter=",",Encoding=65001,QuoteStyle=QuoteStyle.Csv]),
    Headers = Table.PromoteHeaders(Source,[PromoteAllScalars=true]),
    Typed = Table.TransformColumnTypes(Headers,{{"id", type text},{"population", Int64.Type},{"assigned", Int64.Type},{"unassigned", Int64.Type},{"priority_served", Int64.Type},{"priority_unassigned", Int64.Type}})
in
    Typed
