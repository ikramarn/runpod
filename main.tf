terraform {
  required_providers {
    runpod = {
      source  = "decentralized-infrastructure/runpod"
      version = "~> 1.0"
    }
  }
}

provider "runpod" {
  api_key = var.runpod_api_key
}

variable "runpod_api_key" {
  type      = string
  sensitive = true
}

variable "runpod_data_center" {
  type        = string
  default     = "EUR-IS-2"
  description = "RunPod data-center ID for the Pod and, when selected, its network volume."
}

variable "persistent_storage_mode" {
  type        = string
  default     = "pod_volume"
  description = "Persistent storage type: pod_volume for EUR-IS-2, or network_volume in a supported data center."

  validation {
    condition = contains([
      "pod_volume",
      "network_volume",
    ], var.persistent_storage_mode)
    error_message = "Choose either pod_volume or network_volume."
  }
}

variable "pod_volume_size" {
  type        = number
  default     = 50
  description = "Size in GB of the Pod-bound volume mounted at /workspace."
}

locals {
  network_volume_data_centers = toset([
    "AP-IN-2",
    "AP-JP-1",
    "CA-MTL-3",
    "CA-MTL-4",
    "EU-FR-1",
    "EU-NL-1",
    "EU-RO-1",
    "EUR-IS-1",
    "EUR-IS-3",
    "EUR-IS-4",
    "EUR-IS-5",
    "EUR-NO-1",
    "EUR-NO-2",
    "US-CA-2",
    "US-CO-1",
    "US-IL-1",
    "US-KS-2",
    "US-MO-2",
    "US-NC-2",
    "US-NE-1",
    "US-TX-3",
    "US-WA-1",
  ])
}

variable "runpod_cloud_type" {
  type        = string
  default     = "SECURE"
  description = "RunPod cloud type used for the pod."

  validation {
    condition     = contains(["COMMUNITY", "SECURE"], var.runpod_cloud_type)
    error_message = "Choose either COMMUNITY or SECURE."
  }
}

resource "runpod_network_volume" "ai_storage" {
  count          = var.persistent_storage_mode == "network_volume" ? 1 : 0
  name           = "automation-storage"
  size           = var.pod_volume_size
  data_center_id = var.runpod_data_center

  lifecycle {
    prevent_destroy = true
  }
}

resource "terraform_data" "bootstrap_revision" {
  input = filesha256("${path.module}/youtube-automation/bootstrap.sh")
}

resource "runpod_pod" "ai_worker" {
  name      = "paperclip-gpu-worker"
  gpu_count = 1
  # RunPod REST currently rejects this newer GPU ID; use deploy-mig-pod.ps1 instead.
  gpu_type_ids = [
    "NVIDIA RTX PRO 6000 Blackwell Server Edition",
  ]
  gpu_type_priority    = "availability"
  data_center_ids      = [var.runpod_data_center]
  data_center_priority = "custom"
  cloud_type           = var.runpod_cloud_type
  image_name           = "runpod/pytorch:1.1.0-cu1281-torch280-ubuntu2204-cluster"
  network_volume_id    = var.persistent_storage_mode == "network_volume" ? runpod_network_volume.ai_storage[0].id : null
  volume_in_gb         = var.pod_volume_size
  ports                = []

  env = {
    "HOME"                         = "/workspace/paperclip-home"
    "OLLAMA_MODELS"                = "/workspace/ollama-models"
    "OLLAMA_HOST"                  = "127.0.0.1:11434"
    "PAPERCLIP_TELEMETRY_DISABLED" = "1"
  }

  docker_start_cmd = ["/bin/bash", "-c", file("${path.module}/youtube-automation/bootstrap.sh")]

  lifecycle {
    replace_triggered_by = [terraform_data.bootstrap_revision]

    precondition {
      condition     = var.persistent_storage_mode != "network_volume" || contains(local.network_volume_data_centers, var.runpod_data_center)
      error_message = "Network volumes must be created in the Pod's data center. EUR-IS-2 does not support network volumes; use pod_volume there or move the Pod to a supported data center."
    }
  }
}

output "pod_id" {
  value       = runpod_pod.ai_worker.id
  description = "RunPod pod ID"
}

output "pod_public_ip" {
  value       = runpod_pod.ai_worker.public_ip
  description = "Public IP assigned to the pod, when available"
}

