param namespaceName string
param location string

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    kafkaEnabled: true
    minimumTlsVersion: '1.2'
    isAutoInflateEnabled: false
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource hl7 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  name: 'hl7-v2'
  parent: namespace
  properties: {
    partitionCount: 4
    messageRetentionInDays: 7
  }
}

resource fhir 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  name: 'fhir-r4'
  parent: namespace
  properties: {
    partitionCount: 4
    messageRetentionInDays: 7
  }
}

output namespaceName string = namespace.name
output hl7Hub string = hl7.name
output fhirHub string = fhir.name
