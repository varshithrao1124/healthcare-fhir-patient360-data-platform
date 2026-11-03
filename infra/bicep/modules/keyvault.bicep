param name string
param location string
param tenantId string

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take(replace(name, '-', ''), 24)
  location: location
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

output name string = vault.name
output uri string = vault.properties.vaultUri
