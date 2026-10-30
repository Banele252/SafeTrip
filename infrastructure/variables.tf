variable "repository_name" {
  description = "Name of the GitHub repository."
  type        = string
  default     = "SafeTrip"
}

variable "repository_description" {
  description = "Short description shown on the GitHub repository page."
  type        = string
  default     = "Detect and describe what a Raspberry Pi camera sees, and send it to an API."
}

variable "github_owner" {
  description = "GitHub organisation that owns the repository. Leave null to use the token's own account."
  type        = string
  default     = null
}
