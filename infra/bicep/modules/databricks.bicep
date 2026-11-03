param name string
param location string
param managedResourceGroupId string

resource workspace 'Microsoft.Databricks/workspaces@2024-05-01' = {
  name: name
  location: location
  sku: { name: 'premium' }
  properties: {
    managedResourceGroupId: managedResourceGroupId
    publicNetworkAccess: 'Enabled'
  }
}

output name string = workspace.name
output workspaceId string = workspace.id
