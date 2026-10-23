#!/bin/sh
# deploy_command of Antagor (`antagor publish`): push main with tags to origin (Gitea).
# Antagor runs commands without a shell, so && lives here.
set -e
git push origin main --follow-tags
