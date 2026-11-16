variable "region" {
  description = "AWS region for the bucket. Keep it the same as the Elastic Cloud deployment."
  type        = string
  default     = "eu-central-1"
}

variable "profile" {
  description = "AWS CLI profile (SSO or similar) used by Terraform. Null uses the default credential chain."
  type        = string
  default     = null
}

variable "bucket_prefix" {
  description = "Bucket name prefix; a random suffix is appended because bucket names are global."
  type        = string
  default     = "coldchain"
}

variable "object_lock_days" {
  description = "Default governance-mode retention. Short in the demo so teardown stays possible."
  type        = number
  default     = 7
}

# SA sandbox tagging (hive-mind: hive-sa-cloud-tagging). Policy denies creates without these.
variable "project_tag" {
  description = "Owner identity: email local-part with special characters stripped, optional -<demo> suffix."
  type        = string
  default     = "dimitri-coldchain"
}

variable "team" {
  description = "Team from the FE Tagging Guide wiki allowlist (underscored)."
  type        = string
  default     = "emea_dach_area"
}

variable "keep_until" {
  description = "Lease end, YYYY-MM-DD, at most about 13 months out. Use 30-90 days for a demo."
  type        = string
  default     = "2027-02-07"
}
