// Lab 02 infrastructure: a Foundry project with one model deployment for the agents,
// plus Application Insights so agent orchestration runs can be traced.

targetScope = 'resourceGroup'
param location string = resourceGroup().location
param environmentName string
param modelDeploymentName string
param modelName string = modelDeploymentName
param modelVersion string
@description('Sandbox only. Enables public access for standalone lab use. Setting false does not create private endpoints or private DNS.')
param enableSandboxPublicNetworkAccess bool = true
var suffix = uniqueString(subscription().id, resourceGroup().id, environmentName)
var accountName = 'fdry${take(suffix, 18)}'
var projectName = 'lab02-${take(environmentName, 12)}'
var workspaceName = 'log-lab02-${take(suffix, 18)}'
var insightsName = 'appi-lab02-${take(suffix, 18)}'

// Foundry resource (AIServices account). Hosts the model deployment and the project.
// allowProjectManagement makes this a Foundry resource that can contain projects;
// customSubDomainName is what makes the <name>.services.ai.azure.com endpoint and Entra ID auth work.
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
	name: accountName
	location: location
	kind: 'AIServices'
	sku: { name: 'S0' }
	identity: { type: 'SystemAssigned' }
	properties: {
		allowProjectManagement: true
		customSubDomainName: accountName
		publicNetworkAccess: enableSandboxPublicNetworkAccess ? 'Enabled' : 'Disabled'
		networkAcls: { defaultAction: enableSandboxPublicNetworkAccess ? 'Allow' : 'Deny' }
	}
}

// Foundry project: the workspace the lab's Python code connects to (via FOUNDRY_PROJECT_ENDPOINT)
// to create and run agents.
// dependsOn the model deployment to serialize child operations on the account; creating
// the project and deployment in parallel can fail with a conflict on the parent account.
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
	parent: account
	name: projectName
	location: location
	identity: { type: 'SystemAssigned' }
	properties: { displayName: projectName }
	dependsOn: [
		deployment
	]
}

// Log Analytics workspace: storage backend for the Application Insights telemetry below.
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
	name: workspaceName
	location: location
	properties: {
		retentionInDays: 30
		sku: { name: 'PerGB2018' }
	}
}

// Application Insights: receives OpenTelemetry traces of agent runs (tool calls, handoffs,
// model calls) so the multi-agent orchestration can be inspected.
resource insights 'Microsoft.Insights/components@2020-02-02' = {
	name: insightsName
	location: location
	kind: 'web'
	properties: {
		Application_Type: 'web'
		WorkspaceResourceId: workspace.id
	}
}

// Project connection to Application Insights. This is what enables the Foundry portal's
// Tracing view for the project, and lets the SDK look up the App Insights connection string
// from the project instead of the lab code needing it as a separate setting.
resource tracingConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
	parent: project
	name: insights.name
	properties: {
		category: 'AppInsights'
		target: insights.id
		authType: 'ApiKey'
		credentials: { key: insights.properties.ConnectionString }
		metadata: {
			ApiType: 'Azure'
			ResourceId: insights.id
			location: location
		}
	}
}

// Model deployment the agents call. Its name (not the underlying model name) is what the
// lab code references, exported as FOUNDRY_MODEL_NAME.
// Capacity 10 = 10K tokens/min, enough for the lab but may throttle under heavy runs.
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
	parent: account
	name: modelDeploymentName
	sku: { name: 'GlobalStandard', capacity: 10 }
	properties: {
		model: { format: 'OpenAI', name: modelName, version: modelVersion }
		versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
	}
}

// Outputs become environment variables (e.g. written to .env by azd) consumed by the lab code.
output FOUNDRY_PROJECT_ENDPOINT string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output FOUNDRY_PROJECT_ID string = project.id
output FOUNDRY_MODEL_NAME string = deployment.name
output APPLICATIONINSIGHTS_RESOURCE_ID string = insights.id
// customerId is the workspace GUID used for querying logs, not the ARM resource ID.
output LOG_ANALYTICS_WORKSPACE_ID string = workspace.properties.customerId
