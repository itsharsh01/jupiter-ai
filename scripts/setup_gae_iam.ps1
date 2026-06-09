# One-time IAM fixes for App Engine deploy on a new GCP project.
# Usage: .\scripts\setup_gae_iam.ps1 -ProjectId jupiter-ai-498513

param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId
)

$projectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
if (-not $projectNumber) { throw "Could not resolve project number for $ProjectId" }

$appspot = "$ProjectId@appspot.gserviceaccount.com"
$cloudBuild = "$projectNumber@cloudbuild.gserviceaccount.com"
$stagingBucket = "gs://staging.$ProjectId.appspot.com"

Write-Host "Granting storage.admin on $stagingBucket to $appspot"
gcloud storage buckets add-iam-policy-binding $stagingBucket `
    --member="serviceAccount:$appspot" `
    --role="roles/storage.admin" `
    --project=$ProjectId

Write-Host "Granting artifactregistry.writer to Cloud Build and appspot"
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$cloudBuild" `
    --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$appspot" `
    --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$cloudBuild" `
    --role="roles/iam.serviceAccountUser"

Write-Host "Done. Wait ~30s for IAM propagation, then: gcloud app deploy app.yaml --project=$ProjectId"
