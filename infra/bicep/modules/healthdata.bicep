param workspaceName string
param fhirName string
param location string
param tenantId string

resource health 'Microsoft.HealthcareApis/workspaces@2024-03-31' = {
  name: workspaceName
  location: location
  properties: {}
}

resource fhir 'Microsoft.HealthcareApis/workspaces/fhirservices@2024-03-31' = {
  name: fhirName
  parent: health
  location: location
  kind: 'fhir-R4'
  properties: {
    authenticationConfiguration: {
      authority: '${environment().authentication.loginEndpoint}${tenantId}'
      audience: 'https://${workspaceName}-${fhirName}.fhir.azurehealthcareapis.com'
      smartProxyEnabled: true
    }
    corsConfiguration: {
      allowCredentials: false
      origins: []
      headers: ['*']
      methods: ['GET', 'POST', 'PUT', 'DELETE']
      maxAge: 600
    }
  }
}

output fhirName string = fhir.name
output workspaceName string = health.name
