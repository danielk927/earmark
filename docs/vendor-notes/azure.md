# Azure vendor notes (Earmark)

Researched 2026-10-24 by a read-only research agent.
Every claim has a source URL.
Anything not confirmed against an official page is marked UNVERIFIED.
Nothing in this file has been executed against a real Azure subscription yet.

## TL;DR

- **Dashboard:** Azure Static Web Apps, Free plan.
  Create the resource with `az staticwebapp create` (no GitHub needed), then upload `dashboard/dist` with `swa deploy --deployment-token ... --env production`.
- **Memory agent:** Azure Container Apps, Consumption plan, no ingress, `--min-replicas 1 --max-replicas 1`, secrets via `--secrets` plus `secretref:` env vars.
- **Biggest risk:** ACR Tasks (the cloud image build that `az containerapp up --source` relies on) are paused for subscriptions on Azure free credits, and Docker is not installed on this Mac.
  Section 5 gives the order of attempts.
- **Second risk:** Azure for Students subscriptions are commonly restricted to a small per-subscription set of regions by an Azure Policy.
  Check the allowed regions before creating anything (section 3).
- **Local tooling:** `az` is not installed.
  Install with `brew update && brew install azure-cli`.
- **Azure for Students:** $100 credit for 12 months, full-time university students, sign up with a school email, no credit card required.

## 1. Azure for Students

| Fact | Detail | Source |
|---|---|---|
| Credit | $100 USD, usable within 12 months | https://azure.microsoft.com/en-us/free/students |
| Eligibility | "Available only to full-time university students"; "Use your school email to sign up and renew yearly while you're a student." | https://azure.microsoft.com/en-us/free/students |
| Credit card | "No credit card required." | https://azure.microsoft.com/en-us/free/students |
| Accounts | "There is a limit of one account per person." | https://azure.microsoft.com/en-us/free/students |
| Sign-up | Start at https://azure.microsoft.com/en-us/free/students (the button links to https://go.microsoft.com/fwlink/?linkid=2062405&clcid=0x409) | https://azure.microsoft.com/en-us/free/students |
| Remaining credit | Shown on the Azure Sponsorships portal, https://www.microsoftazuresponsorships.com/ | https://learn.microsoft.com/en-us/azure/education-hub/azure-dev-tools-teaching/azure-students-program |
| End of credit | "After you exhaust your available credit or reach the end of 12 months, your Azure subscription is canceled." You can renew while still a student, or upgrade to pay-as-you-go. | https://learn.microsoft.com/en-us/azure/education-hub/azure-dev-tools-teaching/azure-students-program |
| Offer terms | https://azure.microsoft.com/offers/ms-azr-0170p/ (linked from the Learn page, not fetched) | https://learn.microsoft.com/en-us/azure/education-hub/azure-dev-tools-teaching/azure-students-program |

Services the students page lists as "always free" include App Service, Azure Functions, Azure Container Apps, Static Web Apps, Azure Cosmos DB, Azure Monitor, Content Safety, Azure Speech, and others.
Services listed as free for 12 months only include Azure Container Registry, Virtual Machines, and Azure Database for PostgreSQL.
Source: https://azure.microsoft.com/en-us/free/students
"Always free" here means a free monthly amount, not unlimited usage (UNVERIFIED wording; check each service's pricing page).

### Known gotchas on Azure for Students

- **ACR Tasks paused.**
  The ACR Tasks overview says: "Azure Container Registry task runs are temporarily paused from Azure free credits. This pause might affect existing task runs. If you encounter problems, open a support case".
  Source: https://learn.microsoft.com/en-us/azure/container-registry/container-registry-tasks-overview
  A Microsoft employee confirmed the pause applies to subscriptions "using Azure trial credits" when asked about Azure for Students (2024-05-01).
  Source: https://learn.microsoft.com/en-us/answers/questions/1661967/does-the-azure-for-students-subscription-allow-one
  The error looks like `(TasksOperationsNotAllowed) ACR Tasks requests for the registry ... are not permitted.`
  Community threads report that converting to pay-as-you-go lifts it (anecdotal).
  Source: https://learn.microsoft.com/en-us/answers/questions/1530524/how-to-fix-tasksoperationsnotallowed-acr-tasks-req
- **Region restriction policy.**
  Students report `RequestDisallowedByAzure: This policy maintains a set of best available regions where your subscription can deploy resources...` in many regions, including East US and West Europe (2026-08-24).
  The allowed list is per subscription and is visible in the portal under Policy, then Assignments, then "Allowed resource deployment regions" (answer is AI-generated on the Q&A page, so UNVERIFIED).
  Sources: https://learn.microsoft.com/en-us/answers/questions/5983903/region-deployment-for-azure-for-students-subscript and https://learn.microsoft.com/en-us/answers/questions/5949579/azure-for-students-subscription-cannot-deploy-any
  Static Web Apps only supports a few resource regions, so the intersection with the allowed list can be empty (anecdotal).
  Sources: https://learn.microsoft.com/en-us/answers/questions/5669659/static-web-app-deployment-fails-due-to-region-poli and https://learn.microsoft.com/en-us/answers/questions/5783365/cant-select-allowed-region-for-static-web-app-laun

## 2. Local tooling status (checked on this Mac, 2026-10-24)

| Tool | Status | Install |
|---|---|---|
| `az` (Azure CLI) | Not installed (`which az` prints "az not found") | `brew update && brew install azure-cli` (or `brew update && brew install --cask azure-cli`); requires macOS 13+; current version 2.91.0. Source: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos |
| `swa` (Static Web Apps CLI) | Not installed; latest npm version is 2.1.0 | `npm install -g @azure/static-web-apps-cli`, verify with `swa --version`. Source: https://azure.github.io/static-web-apps-cli/docs/use/install |
| `docker` | Not installed | Only needed for the fallback build path in section 5.3 |
| Node / npm | Node v26.10.0 at `/opt/homebrew/bin/node` | Node 26 compatibility with SWA CLI 2.1.0 is UNVERIFIED |
| Rosetta 2 | Available (`arch -x86_64 /usr/bin/true` succeeds) | Needed because `swa deploy` downloads an x64-only `StaticSitesClient` binary on macOS. Source: https://github.com/Azure/static-web-apps-cli/issues/1010 |
| Hardware | arm64 (Apple Silicon), macOS 26.5.1 | Container images for Azure must be `linux/amd64` (section 5) |

## 3. One-time setup

```bash
brew update && brew install azure-cli
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

Source for the extension and provider steps: https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up

Find the regions this subscription may deploy to before picking `LOCATION`.
The portal path is Policy, then Assignments, then "Allowed resource deployment regions", then Parameter value.
A CLI equivalent (UNVERIFIED, standard Azure Policy command):

```bash
az policy assignment list --query "[].{name:displayName, params:parameters}" -o json
```

List the regions where Static Web Apps can be created (UNVERIFIED, standard ARM provider query), then pick one that is also on the allowed list:

```bash
az provider show -n Microsoft.Web --query "resourceTypes[?resourceType=='staticSites'].locations | [0]" -o tsv
```

Shared variables used below:

```bash
export RG=earmark-rg
export LOCATION=<allowed-region>       # for example eastus2, only if the policy allows it
export SWA_NAME=earmark-dashboard
export ENV_NAME=earmark-env
export APP_NAME=earmark-memory-agent   # lowercase, letters/digits/'-', under 32 chars
az group create --name $RG --location $LOCATION
```

## 4. Dashboard on Azure Static Web Apps (Free plan)

### 4.1 Why the Free plan is enough

| Free plan limit | Value | Source |
|---|---|---|
| Included bandwidth | 100 GB per month, no overage available | https://learn.microsoft.com/en-us/azure/static-web-apps/quotas |
| Apps per subscription | 10 | https://learn.microsoft.com/en-us/azure/static-web-apps/quotas |
| Storage | 250 MB per environment, 500 MB total | https://learn.microsoft.com/en-us/azure/static-web-apps/quotas |
| File count | 15,000 | https://learn.microsoft.com/en-us/azure/static-web-apps/quotas |
| Custom domains | 2 | https://learn.microsoft.com/en-us/azure/static-web-apps/quotas |
| SSL | Free, auto-renewing certificates | https://learn.microsoft.com/en-us/azure/static-web-apps/plans |
| Static content | Globally distributed | https://learn.microsoft.com/en-us/azure/static-web-apps/plans |
| SLA | None on Free; Standard has an SLA | https://learn.microsoft.com/en-us/azure/static-web-apps/plans |

### 4.2 SPA fallback routing

Put this file at `dashboard/public/staticwebapp.config.json`.
Vite copies everything in `public/` "to the root of the dist directory as-is" (https://vite.dev/guide/assets), and Static Web Apps requires the file at the root of the build output (https://learn.microsoft.com/en-us/azure/static-web-apps/configuration).

```json
{
  "navigationFallback": {
    "rewrite": "/index.html",
    "exclude": ["/assets/*", "/*.{png,jpg,gif,svg,ico,css,js,json,webmanifest}"]
  }
}
```

The `navigationFallback.rewrite` and `exclude` syntax is from https://learn.microsoft.com/en-us/azure/static-web-apps/configuration.
The exclude patterns above are tailored to Vite's default `dist/assets/` layout; that tailoring is ours, not Microsoft's.
Excluded paths return a real 404 when the file is missing, instead of silently serving `index.html`.
The config file has a 20 KB size limit.

### 4.3 Build with the Convex URL

Vite exposes only `VITE_`-prefixed variables, and they are "statically replaced at build time".
Variables already set in the shell "have the highest priority and will not be overwritten by `.env` files".
Source: https://vite.dev/guide/env-and-mode

```bash
cd dashboard
npm ci
VITE_CONVEX_URL="https://<deployment-name>.convex.cloud" npm run build   # writes dashboard/dist
```

Anything in a `VITE_` variable ships inside the public JavaScript bundle.
The Convex deployment URL is meant to be public; never put a secret in a `VITE_` variable.

### 4.4 Create and deploy without GitHub Actions

```bash
# 1. Create an empty Free-plan app with no repository attached.
az staticwebapp create --name $SWA_NAME --resource-group $RG --location $LOCATION --sku Free

# 2. Fetch the deployment token (treat it as a secret; never commit it).
export SWA_CLI_DEPLOYMENT_TOKEN=$(az staticwebapp secrets list --name $SWA_NAME --query "properties.apiKey" -o tsv)

# 3. Upload the built site to the production environment (run from dashboard/).
npm install -g @azure/static-web-apps-cli
swa deploy ./dist --env production

# 4. Print the public URL.
az staticwebapp show --name $SWA_NAME --resource-group $RG --query defaultHostname -o tsv
```

Sources:
- `az staticwebapp create` documents the example "Create a static web app without any content and without a github integration": `az staticwebapp create -n MyStaticAppName -g MyExistingRg`; `--sku` defaults to `Free`; `--location` defaults to `centralus`. https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest
- `az staticwebapp secrets list --name <APPLICATION_NAME> --query "properties.apiKey"`, the `SWA_CLI_DEPLOYMENT_TOKEN` variable, `--deployment-token`, and `--env` (default `preview`, so `--env production` is required for the main URL). https://learn.microsoft.com/en-us/azure/static-web-apps/static-web-apps-cli-deploy
- The `defaultHostname` property name is UNVERIFIED; if it returns nothing, run `az staticwebapp show` without `--query` and read the hostname field.

Notes:
- `swa deploy --dry-run` simulates the deploy without uploading.
- If `swa deploy` prompts to create a `swa-cli.config.json`, accepting the detected defaults is fine (UNVERIFIED that it prompts when given a folder and token).
- If `swa deploy` hangs at "Preparing deployment" or fails with `spawn Unknown system error -86`, the x64 `StaticSitesClient` binary could not run.
  Rosetta is installed here, so this should not happen.
  Sources: https://github.com/Azure/static-web-apps-cli/issues/1010 and https://github.com/Azure/static-web-apps-cli/issues/914
- Rotate a leaked token with `az staticwebapp secrets reset-api-key --name $SWA_NAME`.
  Source: https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest

### 4.5 Fallback if Static Web Apps is blocked by the region policy

Azure Storage static website hosting works in any region the policy allows.

```bash
export SA=earmarkweb$RANDOM   # globally unique, lowercase letters and digits only
az storage account create -n $SA -g $RG -l $LOCATION --sku Standard_LRS --kind StorageV2
az storage blob service-properties update --account-name $SA --static-website --index-document index.html --404-document index.html
az storage blob upload-batch -s ./dist -d '$web' --account-name $SA
az storage account show -n $SA -g $RG --query "primaryEndpoints.web" --output tsv
```

The `service-properties update`, `upload-batch`, and `primaryEndpoints.web` commands are from https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-static-website-how-to.
The `az storage account create` line is UNVERIFIED (not taken from that page).
Using `index.html` as the 404 document makes client-side routes load, but those responses carry HTTP status 404 (UNVERIFIED for this setup; standard behavior of the error document).

## 5. Memory agent on Azure Container Apps

### 5.1 Option comparison

| Option | Stays running | Build without local Docker | Cost for 0.25 vCPU / 0.5 GiB always on | Verdict |
|---|---|---|---|---|
| **Container Apps (Consumption)** | Yes, with `--min-replicas 1` | `az containerapp up --source` builds in the cloud, but that uses ACR (see 5.3) | A 48-hour demo fits inside the monthly free grant; about $4 to $14 per month after that (5.2) | **Recommended** |
| App Service (Linux B1) | Yes, with Always On (not available on Free) | Yes, code deploy | $0.017 per hour, about $12.41 per 730-hour month (Retail Prices API, East US) | Fallback only; compatibility of a uAgent with App Service's HTTP warmup ping is UNVERIFIED |
| Container Instances | Yes | No, needs a prebuilt image | Billed per second for vCPU and memory, no free grant found | Not recommended |

Sources:
- App Service: "When **Always On** is turned off (default), the app is unloaded after 20 minutes without any incoming requests." https://learn.microsoft.com/en-us/azure/app-service/configure-common
- Container Instances: "You pay based on what you need and get billed by the second"; "Azure Container Instances supports only x64 (AMD64) container images." https://learn.microsoft.com/en-us/azure/container-instances/container-instances-overview
- Prices: https://prices.azure.com/api/retail/prices (queried 2026-10-24 for `Azure App Service` B1 and `Azure Container Apps` in `eastus`).

### 5.2 Constraints and cost

- Images must be `linux/amd64`: "Any Linux-based x86-64 (`linux/amd64`) container image"; "Linux-based (`linux/amd64`) container images are required." https://learn.microsoft.com/en-us/azure/container-apps/containers
- Smallest Consumption size is `0.25` vCPU with `0.5Gi` memory. https://learn.microsoft.com/en-us/azure/container-apps/containers
- Without ingress the app scales to zero and never wakes unless you set a minimum: "If ingress is disabled and you don't define a `minReplicas` or a custom scale rule, your container app scales to zero and has no way of starting back up." Default limits are min 0, max 10. https://learn.microsoft.com/en-us/azure/container-apps/scale-app
- Set `--max-replicas 1` as well.
  Two replicas would run the same agent seed and poll the same mailbox; that is our reasoning, not Microsoft guidance.
- Free grant: "The first 180,000 vCPU-seconds, 360,000 GiB-seconds, and 2 million requests per subscription per month are free." https://azure.microsoft.com/en-us/pricing/details/container-apps/
- Idle billing: "A replica is active when vCPU usage is above 0.01 cores or when data received is above 1,000 bytes per second"; otherwise a minimum replica bills at the lower idle rate. https://azure.microsoft.com/en-us/pricing/details/container-apps/
- East US list prices from the Retail Prices API: vCPU active $0.000024 per second, vCPU idle $0.000003 per second, memory $0.000003 per GiB-second.

Cost math for one 0.25 vCPU / 0.5 GiB replica:

| Period | vCPU-seconds | GiB-seconds | Cost |
|---|---|---|---|
| 48-hour hackathon | 43,200 | 86,400 | $0, within the free grant |
| 30-day month | 648,000 (468,000 billable) | 1,296,000 (936,000 billable) | About $4.21 if idle the whole time, about $14.04 if active the whole time |

Whether a mailbox-polling uAgent stays under the idle thresholds is UNVERIFIED.
Log Analytics ingestion (created by default with the environment) is billed separately; its price was not checked.

### 5.3 Build path, in order of preference

**Path A: `az containerapp up --source` (no local Docker).**
It "builds the container image, pushes it to a registry, and deploys the container app. If you don't specify a registry, the command creates one in Container Registry."
Python builds work with or without a Dockerfile.
Source: https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up
That build runs on ACR Tasks, which are paused on free-credit subscriptions (section 1).
Expect it to fail with `TasksOperationsNotAllowed` on Azure for Students; try it once anyway because it is the shortest path.
UNVERIFIED: the no-Dockerfile path mentions a "Cloud Build agent", which may or may not use ACR Tasks; if the Dockerfile build fails, retrying without a Dockerfile is a cheap second attempt.

**Path B: build locally, push to ACR Basic, deploy the image.**
Requires installing Docker (for example Docker Desktop via `brew install --cask docker`, then open Docker.app once).
ACR Basic costs $0.1666 per day (Retail Prices API, East US), and the students page lists Container Registry as free for 12 months (tier not stated).

**Path C: App Service B1 code deploy.**
Only if both container paths fail; see 5.1 for the caveats.
Commands are not included here because the App Service flow for a non-web Python process was not verified.

### 5.4 Path A commands

```bash
az containerapp env create --name $ENV_NAME --resource-group $RG --location $LOCATION

cd services/memory_agent   # must contain the Dockerfile; no EXPOSE line, so no ingress is configured
az containerapp up \
  --name $APP_NAME \
  --resource-group $RG \
  --location $LOCATION \
  --environment $ENV_NAME \
  --source .
```

`up` has no `--min-replicas` or `--secrets` flags, so configure those right after.
"If you want to customize other settings for your container app, such as resource or scaling settings, first use the `up` command to deploy your container app. Then use the `az containerapp update` command".
Source: https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up
The first revision will crash-loop until the secrets below exist; that is expected.

```bash
# Secret names: lowercase, '-' allowed, at most 20 characters.
az containerapp secret set --name $APP_NAME --resource-group $RG \
  --secrets agent-seed="$AGENT_SEED" bitdeer-api-key="$BITDEER_API_KEY"

# Creates a new revision that reads the secrets, pins one replica, and sets the size.
az containerapp update --name $APP_NAME --resource-group $RG \
  --min-replicas 1 --max-replicas 1 \
  --cpu 0.25 --memory 0.5Gi \
  --set-env-vars AGENT_SEED=secretref:agent-seed BITDEER_API_KEY=secretref:bitdeer-api-key CONVEX_URL="https://<deployment-name>.convex.cloud"
```

Env var names above are placeholders; use whatever `services/memory_agent` reads.
Sources:
- `az containerapp secret set --secrets` and the 20-character key limit: https://learn.microsoft.com/en-us/cli/azure/containerapp/secret?view=azure-cli-latest
- `secretref:` syntax: "Prefix value with 'secretref:' to reference a secret." https://learn.microsoft.com/en-us/cli/azure/containerapp?view=azure-cli-latest
- `az containerapp update ... --cpu 0.5 --memory 1.0Gi --min-replicas 4 --max-replicas 8` example: https://learn.microsoft.com/en-us/cli/azure/containerapp?view=azure-cli-latest
- Changing a secret does not restart existing revisions: "When a secret is updated or deleted, you can respond to changes in one of two ways: 1. Deploy a new revision. 2. Restart an existing revision." https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets

Redeploy after code changes:

```bash
az containerapp up --name $APP_NAME --source . --resource-group $RG --environment $ENV_NAME
```

Confirm min and max replicas survive a redeploy (UNVERIFIED; `up` may reset scale settings).

### 5.5 Path B commands (local Docker plus ACR)

```bash
export ACR=earmarkacr$RANDOM   # globally unique, alphanumeric
az acr create --name $ACR --resource-group $RG --location $LOCATION --sku Basic
az acr login --name $ACR
docker buildx build --platform linux/amd64 -t $ACR.azurecr.io/memory-agent:v1 --push services/memory_agent

az containerapp env create --name $ENV_NAME --resource-group $RG --location $LOCATION
az containerapp create --name $APP_NAME --resource-group $RG --environment $ENV_NAME \
  --image $ACR.azurecr.io/memory-agent:v1 \
  --registry-server $ACR.azurecr.io --registry-identity system \
  --min-replicas 1 --max-replicas 1 --cpu 0.25 --memory 0.5Gi \
  --secrets agent-seed="$AGENT_SEED" bitdeer-api-key="$BITDEER_API_KEY" \
  --env-vars AGENT_SEED=secretref:agent-seed BITDEER_API_KEY=secretref:bitdeer-api-key
```

Sources:
- `az containerapp create` with `--secrets` and `--env-vars ... SECRETENV=secretref:anothersecret`: https://learn.microsoft.com/en-us/cli/azure/containerapp?view=azure-cli-latest
- `--registry-identity`: "Use a resource ID or 'system' for user-defined and system-defined identities ... If possible, an 'acrpull' role assignment will be created for the identity automatically." https://learn.microsoft.com/en-us/cli/azure/containerapp?view=azure-cli-latest
- `az acr create`, `az acr login`, and the `docker buildx` line are UNVERIFIED (standard commands, not fetched this session).

If `--registry-identity system` fails, enable the ACR admin user and pass `--registry-username` and `--registry-password` instead (UNVERIFIED fallback).
Use a new tag per build; Microsoft advises against static tags like `latest`. https://learn.microsoft.com/en-us/azure/container-apps/containers

### 5.6 Fetch.ai mailbox caveat for a cloud-hosted agent

Mailbox registration is done once through the Agentverse Inspector link the agent prints at startup.
That link points at the agent's local HTTP server (`uri=http://127.0.0.1:8000`), and the Inspector page in the browser connects to it.
Once registered, the agent only needs outbound connections; the mailbox holds messages until the agent collects them.
Source: https://uagents.fetch.ai/docs/agentverse/mailbox
An agent in Container Apps with no ingress cannot be reached by that browser step.
Two options, both UNVERIFIED:
1. Run the agent locally once with the same seed, register the mailbox through the Inspector, then deploy to Azure with that seed (the agent address is derived from the seed).
2. Temporarily add ingress (`az containerapp ingress enable --name $APP_NAME --resource-group $RG --type external --target-port 8000`) and open the Inspector with the app's HTTPS URL.

Check `docs/vendor-notes/fetchai.md` (if present) for the authoritative registration flow.

### 5.7 Operate and tear down

```bash
# Live console logs (default type is console).
az containerapp logs show --name $APP_NAME --resource-group $RG --follow

# Platform/system events, for example image pull or crash-loop reasons.
az containerapp logs show --name $APP_NAME --resource-group $RG --type system --tail 50

# Delete everything when the hackathon is over.
az group delete --name $RG --yes --no-wait
```

Log commands: https://learn.microsoft.com/en-us/azure/container-apps/log-streaming
`az group delete` deletes every resource in the group: https://learn.microsoft.com/en-us/azure/container-apps/quickstart-code-to-cloud

## 6. Production-path talking points (for `docs/PRODUCTION.md`)

- Static Web Apps Standard plan adds an SLA, custom auth providers, and private endpoints. https://learn.microsoft.com/en-us/azure/static-web-apps/plans
- Microsoft says to avoid literal secret values in production and use Key Vault references with a managed identity. https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets
- Container Apps scales on HTTP, TCP, or KEDA event sources, so one agent per household can grow into a pool driven by queue length. https://learn.microsoft.com/en-us/azure/container-apps/scale-app
- Use managed identity for registry pulls instead of registry passwords. https://learn.microsoft.com/en-us/azure/container-apps/containers
- Microsoft's responsible AI "Operate" stage asks for a phased delivery plan, incident response plan, rollback plan, and user feedback channels; see `docs/sponsor-packs/microsoft.md`.

## Sources

- https://azure.microsoft.com/en-us/free/students
- https://learn.microsoft.com/en-us/azure/education-hub/azure-dev-tools-teaching/azure-students-program
- https://learn.microsoft.com/en-us/azure/container-registry/container-registry-tasks-overview
- https://learn.microsoft.com/en-us/answers/questions/1661967/does-the-azure-for-students-subscription-allow-one
- https://learn.microsoft.com/en-us/answers/questions/1530524/how-to-fix-tasksoperationsnotallowed-acr-tasks-req
- https://learn.microsoft.com/en-us/answers/questions/5983903/region-deployment-for-azure-for-students-subscript
- https://learn.microsoft.com/en-us/answers/questions/5949579/azure-for-students-subscription-cannot-deploy-any
- https://learn.microsoft.com/en-us/answers/questions/5669659/static-web-app-deployment-fails-due-to-region-poli
- https://learn.microsoft.com/en-us/answers/questions/5783365/cant-select-allowed-region-for-static-web-app-laun
- https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos
- https://azure.github.io/static-web-apps-cli/docs/use/install
- https://github.com/Azure/static-web-apps-cli/issues/1010
- https://github.com/Azure/static-web-apps-cli/issues/914
- https://learn.microsoft.com/en-us/azure/static-web-apps/static-web-apps-cli-deploy
- https://learn.microsoft.com/en-us/azure/static-web-apps/configuration
- https://learn.microsoft.com/en-us/azure/static-web-apps/plans
- https://learn.microsoft.com/en-us/azure/static-web-apps/quotas
- https://learn.microsoft.com/en-us/cli/azure/staticwebapp?view=azure-cli-latest
- https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-static-website-how-to
- https://vite.dev/guide/env-and-mode
- https://vite.dev/guide/assets
- https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up
- https://learn.microsoft.com/en-us/azure/container-apps/quickstart-code-to-cloud
- https://learn.microsoft.com/en-us/azure/container-apps/containers
- https://learn.microsoft.com/en-us/azure/container-apps/scale-app
- https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets
- https://learn.microsoft.com/en-us/azure/container-apps/log-streaming
- https://learn.microsoft.com/en-us/cli/azure/containerapp?view=azure-cli-latest
- https://learn.microsoft.com/en-us/cli/azure/containerapp/secret?view=azure-cli-latest
- https://learn.microsoft.com/en-us/cli/azure/containerapp/env?view=azure-cli-latest
- https://azure.microsoft.com/en-us/pricing/details/container-apps/
- https://prices.azure.com/api/retail/prices
- https://learn.microsoft.com/en-us/azure/app-service/configure-common
- https://learn.microsoft.com/en-us/azure/container-instances/container-instances-overview
- https://uagents.fetch.ai/docs/agentverse/mailbox
