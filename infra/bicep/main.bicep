targetScope = 'resourceGroup'

@description('Short environment token, such as dev or prod.')
param environment string = 'dev'

@description('Azure region for the clinical platform.')
param location string = resourceGroup().location

@description('Globally unique suffix for storage and Event Hubs names.')
param uniqueSuffix string

@description('Entra tenant used by the FHIR service.')
param tenantId string

@description('Resource group Databricks creates for its own managed resources.')
param databricksManagedRg string = 'rg-acn-northline-dbw-managed'

var prefix = 'acn-nl-${environment}'

module logs 'modules/monitor.bicep' = {
  name: 'logs'
  params: {
    name: '${prefix}-logs'
    location: location
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    name: 'acnnl${environment}${uniqueSuffix}'
    location: location
  }
}

module vault 'modules/keyvault.bicep' = {
  name: 'vault'
  params: {
    name: '${prefix}-kv-${uniqueSuffix}'
    location: location
    tenantId: tenantId
  }
}

module hubs 'modules/eventhubs.bicep' = {
  name: 'hubs'
  params: {
    namespaceName: '${prefix}-eh-${uniqueSuffix}'
    location: location
  }
}

module factory 'modules/datafactory.bicep' = {
  name: 'factory'
  params: {
    name: '${prefix}-orch'
    location: location
  }
}

module warehouse 'modules/databricks.bicep' = {
  name: 'warehouse'
  params: {
    name: '${prefix}-dbw'
    location: location
    managedResourceGroupId: subscriptionResourceId('Microsoft.Resources/resourceGroups', databricksManagedRg)
  }
}

module fhir 'modules/healthdata.bicep' = {
  name: 'fhir'
  params: {
    workspaceName: '${prefix}-health'
    fhirName: '${prefix}-fhir'
    location: location
    tenantId: tenantId
  }
}

output storageAccountName string = storage.outputs.name
output keyVaultName string = vault.outputs.name
output eventHubNamespace string = hubs.outputs.namespaceName
output fhirServiceName string = fhir.outputs.fhirName
output logAnalyticsWorkspaceId string = logs.outputs.workspaceId
output dataFactoryName string = factory.outputs.name
output databricksWorkspaceName string = warehouse.outputs.name
