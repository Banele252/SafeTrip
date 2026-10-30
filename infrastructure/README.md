# Infrastructure

Terraform that creates the public GitHub repository for SafeTrip.

## Prerequisites

- Terraform 1.5 or newer.
- A GitHub personal access token with permission to create repositories, exported as `GITHUB_TOKEN` in your shell:

  ```bash
  export GITHUB_TOKEN=ghp_...
  ```

The token is read from the environment and is never written to Terraform files.

## Create the repository

```bash
cd infrastructure
terraform init
terraform plan
terraform apply
```

Then connect the local repository and push it:

```bash
cd ..
git remote add origin "$(terraform -chdir=infrastructure output -raw ssh_clone_url)"
git push -u origin master
```

## Notes

- `terraform.tfstate` is stored locally and gitignored. If you lose it, re-attach the existing repository with:

  ```bash
  terraform import github_repository.safetrip SafeTrip
  ```

- The repository is public. Check that everything you commit is safe to publish before pushing.
- To create the repository under an organisation, set `github_owner` in a `terraform.tfvars` file, or pass `-var github_owner=your-org`.
