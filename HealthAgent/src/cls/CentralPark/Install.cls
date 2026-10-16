/// Boot-time installer. Called from iris.script after classes are loaded
/// into the CENTRALPARK namespace. Lives in a compiled class because that's
/// the only way we get multi-line brace blocks and try/catch in this codebase,
/// since iris.script is parsed line by line.
Class CentralPark.Install Extends %RegisteredObject
{

Parameter NAMESPACE = "CENTRALPARK";
Parameter ENDPOINT = "/csp/healthshare/centralpark/fhir/r4";
Parameter STRATEGY = "HS.FHIRServer.Storage.Json.InteractionsStrategy";
Parameter METADATA = "hl7.fhir.r4.core@4.0.1";
Parameter RESTAPP = "/centralpark";
Parameter SSLCONFIG = "openai-ssl";
Parameter EMBEDDINGCONFIG = "central-park-openai";

ClassMethod Run() As %Status
{
    set sc = ..ConfigureCredentials()
    if 'sc quit sc
    // Note: %EnsembleMgr.EnableNamespace auto-installs HealthShare Foundation
    // for IRIS for Health, so no explicit Foundation install step is needed.
    do ..InstallFHIRServer()
    do ..InstallRESTApp()
    do ..InstallSSLConfig()
    do ..InstallEmbeddingConfig()
    do ..SeedFHIR()
    quit $$$OK
}

/// Configure the local service account for non-interactive HTTP Basic login.
/// The base image can require a password change and its first-run entrypoint
/// is already marked initialized during our build. Apply settings on each
/// container start too, including when an existing database volume is reused.
ClassMethod ConfigureCredentials() As %Status
{
    set saveNS = $namespace, sc = $$$OK
    try {
        set $namespace = "%SYS"
        set username = $system.Util.GetEnviron("IRIS_USERNAME")
        if username="" set username="_SYSTEM"
        set password = $system.Util.GetEnviron("IRIS_PASSWORD")
        if password="" set password="SYS"
        if ##class(Security.Users).Exists(username) {
            set props("Password") = password
            set props("ChangePassword") = 0
            set sc = ##class(Security.Users).Modify(username, .props)
        } else {
            set sc = ##class(Security.Users).Create(username, "%All", password, "Central Park service account", ..#NAMESPACE, , , 0, 1)
        }
    } catch ex {
        set sc = ex.AsStatus()
    }
    set $namespace = saveNS
    quit sc
}

/// Create an outbound TLS configuration named "openai-ssl" so
/// %Embedding.OpenAI can reach api.openai.com. We use VerifyPeer=0 (no peer
/// verification) for a frictionless demo; for production use, configure a CA
/// bundle and set VerifyPeer=2.
ClassMethod InstallSSLConfig()
{
    set saveNS = $namespace
    try {
        set $namespace = "%SYS"
        if ##class(Security.SSLConfigs).Exists(..#SSLCONFIG) {
            write !,"SSL config ",..#SSLCONFIG," already exists."
        } else {
            set props("Description") = "Outbound TLS for OpenAI API"
            set props("VerifyPeer") = 0
            set props("Protocols") = 24 // TLS 1.2
            set sc = ##class(Security.SSLConfigs).Create(..#SSLCONFIG, .props)
            if 'sc {
                write !,"SSL config create failed: ",$system.Status.GetErrorText(sc)
            } else {
                write !,"SSL config ",..#SSLCONFIG," created."
            }
        }
    } catch ex {
        write !,"InstallSSLConfig error: ",ex.DisplayString()
    }
    set $namespace = saveNS
}

/// Refresh model/endpoint/dimensions from the IRIS container's environment.
/// Keep the existing config name; both evidence collections share this config.
/// Never log credentials or reset stored evidence when a model is changed.
ClassMethod InstallEmbeddingConfig() As %Status
{
    set sc = $$$OK
    try {
        set provider=$system.Util.GetEnviron("CP_EMBEDDING_PROVIDER")
        if provider="" set provider="openai"
        if '$listfind($listbuild("openai","openai_compatible","ollama"),provider) throw ##class(%Exception.General).%New("CP_EMBEDDING_PROVIDER must be openai, openai_compatible or ollama")
        set model=$system.Util.GetEnviron("CP_EMBEDDING_MODEL")
        if model="" set model="text-embedding-3-small"
        set dimensions=$system.Util.GetEnviron("CP_EMBEDDING_DIMENSIONS")
        if dimensions="" set dimensions=1536
        if (dimensions'?1N.N)!(dimensions<1)!(dimensions>65536) throw ##class(%Exception.General).%New("CP_EMBEDDING_DIMENSIONS must be an integer from 1 to 65536")
        set apiKey=$system.Util.GetEnviron("CP_EMBEDDING_API_KEY")
        if (apiKey="")&&(provider'="ollama") set apiKey=$system.Util.GetEnviron("OPENAI_API_KEY")
        set base=$system.Util.GetEnviron("CP_EMBEDDING_BASE_URL")
        if base="" set base=$select(provider="ollama":"http://ollama:11434",1:"https://api.openai.com/v1")
        set base=$zstrip(base,">","/")
        do ##class(%Net.URLParser).Parse(base,.url)
        if ('$listfind($listbuild("http","https"),$get(url("scheme"))))!($get(url("host"))="")!($get(url("query"))'="")!($get(url("fragment"))'="")!(base["@") throw ##class(%Exception.General).%New("Invalid CP_EMBEDDING_BASE_URL; use an http(s) API root")
        set send=$zconvert($system.Util.GetEnviron("CP_EMBEDDING_SEND_DIMENSIONS"),"L")
        if send="" set send="false"
        if '$listfind($listbuild("true","false","1","0"),send) throw ##class(%Exception.General).%New("CP_EMBEDDING_SEND_DIMENSIONS must be true or false")
        set jsonCfg = {}
        set jsonCfg."modelName" = model
        set jsonCfg."apiKey" = apiKey
        set jsonCfg."sslConfig" = ..#SSLCONFIG
        set jsonCfg."checkTokenCount" = 0
        set jsonCfg.provider=provider, jsonCfg."baseUrl"=base, jsonCfg.dimensions=+dimensions
        set jsonCfg."sendDimensions"=((send="true")!(send="1"))
        set jsonCfg.revision=$system.Util.GetEnviron("CP_EMBEDDING_REVISION")
        set cfg=##class(%Embedding.Config).%OpenId(..#EMBEDDINGCONFIG)
        if '$isobject(cfg) set cfg = ##class(%Embedding.Config).%New()
        set cfg.Name = ..#EMBEDDINGCONFIG
        set cfg.Description = provider_" "_model_" ("_dimensions_" dimensions)"
        // Preserve the native provider for the existing official OpenAI configuration.
        set cfg.EmbeddingClass=$select((provider="openai")&&(base="https://api.openai.com/v1")&&('jsonCfg."sendDimensions"):"%Embedding.OpenAI",1:"CentralPark.Embedding.HTTP")
        set cfg.Configuration = jsonCfg.%ToJSON()
        set cfg.VectorLength = +dimensions
        set sc = cfg.%Save()
        set ^CentralPark("log","install","embedding-config") = $listbuild($zdatetime($horolog, 3), (apiKey '= ""), $select(sc: "ok", 1: $system.Status.GetErrorText(sc)))
    } catch ex {
        set ^CentralPark("log","install","embedding-config") = $listbuild($zdatetime($horolog, 3), 0, ex.DisplayString())
        set sc = ex.AsStatus()
    }
    quit sc
}

/// Create the FHIR R4 endpoint at ENDPOINT, backed by the JSON storage
/// strategy. Two steps: InstallNamespace registers FHIR metadata for the
/// current namespace; InstallInstance binds the URL to that namespace.
ClassMethod InstallFHIRServer()
{
    set saveNS = $namespace
    try {
        do ##class(HS.FHIRServer.Installer).InstallNamespace()
    } catch ex {
        write !,"InstallNamespace error: ",ex.DisplayString()
    }
    try {
        do ##class(HS.FHIRServer.Installer).InstallInstance(..#ENDPOINT, ..#STRATEGY, $listbuild(..#METADATA))
        write !,"FHIR endpoint installed at ",..#ENDPOINT
    } catch ex {
        write !,"InstallInstance error: ",ex.DisplayString()
    }
    try {
        set $namespace = "%SYS"
        set props("AutheEnabled") = 32 // password authentication, including HTTP Basic
        set sc = ##class(Security.Applications).Modify(..#ENDPOINT, .props)
        if 'sc write !,"FHIR authentication configuration failed: ",$system.Status.GetErrorText(sc)
    } catch ex {
        write !,"FHIR authentication configuration error: ",ex.DisplayString()
    }
    set $namespace = saveNS
}

/// Register /centralpark as a CSP application that dispatches to our REST
/// class. This is a %SYS-namespace operation, so we save/restore $namespace.
ClassMethod InstallRESTApp()
{
    set saveNS = $namespace
    try {
        set $namespace = "%SYS"
        set props("AutheEnabled") = 32                              // password auth
        set props("DispatchClass") = "CentralPark.REST.Dispatch"
        set props("NameSpace") = ..#NAMESPACE
        set props("MatchRoles") = ":%All"
        if ##class(Security.Applications).Exists(..#RESTAPP) {
            set sc = ##class(Security.Applications).Modify(..#RESTAPP, .props)
        } else {
            set sc = ##class(Security.Applications).Create(..#RESTAPP, .props)
        }
        if 'sc write !,"REST application configuration failed: ",$system.Status.GetErrorText(sc)
        write !,"REST app ",..#RESTAPP," registered."
    } catch ex {
        write !,"InstallRESTApp error: ",ex.DisplayString()
    }
    set $namespace = saveNS
}

/// Load the demo patient bundle into the FHIR endpoint. Idempotent: a global
/// marker (^CentralPark("seed", "demo-patient-1")) lets repeated boots skip
/// the POST. The bundle itself uses PUT requests on stable ids, so a manual
/// re-seed is safe too.
ClassMethod SeedFHIR()
{
    if $get(^CentralPark("seed", "demo-patient-1")) {
        write !,"FHIR seed already loaded, skipping."
        quit
    }
    set base = "/home/irisowner/central-park/iris-config/seed/"
    // demo-patient-1.json: the cardiac-risk demo patient (Marcus Reeves).
    // demo-cases.json: three more patients with pre-built triage cases at
    // varied levels so the clinician worklist shows a realistic mixed queue.
    set ok = ..PostBundle(base_"demo-patient-1.json")
    set ok = ..PostBundle(base_"demo-cases.json") && ok
    if ok {
        set ^CentralPark("seed", "demo-patient-1") = $zdatetime($horolog, 3)
        write !,"(marked seeded)"
    }
}

/// POST one FHIR transaction bundle to the local endpoint. Returns 1 on a
/// 200/201 response, 0 otherwise. Bundles use PUT on stable ids, so re-posting
/// is idempotent and a manual re-seed is safe.
ClassMethod PostBundle(bundlePath As %String) As %Boolean
{
    try {
        if '##class(%File).Exists(bundlePath) {
            write !,"Seed bundle not found at ",bundlePath
            return 0
        }
        set stream = ##class(%Stream.FileBinary).%New()
        do stream.LinkToFile(bundlePath)
        set req = ##class(%Net.HttpRequest).%New()
        set req.Server = "localhost"
        set req.Port = 52773
        set req.Username = "_SYSTEM"
        set req.Password = "SYS"
        set req.ContentType = "application/fhir+json"
        do req.SetHeader("Accept", "application/fhir+json")
        do req.EntityBody.CopyFrom(stream)
        set sc = req.Post(..#ENDPOINT)
        if 'sc {
            write !,"Seed POST failed: ",$system.Status.GetErrorText(sc)
            return 0
        }
        set status = req.HttpResponse.StatusCode
        write !,"Seed POST ",bundlePath," status=",status
        return ((status = 200) || (status = 201))
    } catch ex {
        write !,"Seed error: ",ex.DisplayString()
        return 0
    }
}

}
