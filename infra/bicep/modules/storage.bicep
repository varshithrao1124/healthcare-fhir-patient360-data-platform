param name string
param location string

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    accessTier: 'Hot'
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  name: 'default'
  parent: account
}

var containers = ['landing', 'capture', 'conform', 'insight', 'quarantine']

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for item in containers: {
  name: item
  parent: blob
  properties: { publicAccess: 'None' }
}]

output name string = account.name
output id string = account.id
