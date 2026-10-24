#!/bin/bash
set -e

# ============================================================================
# Deploy all 5 AI Team agents to Bedrock AgentCore
# ============================================================================
#
# Usage:
#   AWS_PROFILE=your-profile ./deploy-all.sh          # deploy all
#   AWS_PROFILE=your-profile ./deploy-all.sh ai-gk    # deploy one agent
#
# How it works:
#   1. Creates a _build/<agent>/ staging directory for each agent
#   2. Copies the agent's src/ + shared lib/ + requirements.txt into it
#   3. Generates .bedrock_agentcore.yaml from the agent's template
#   4. Deploys from the staging directory
#   5. Injects the tactical-tools URL into ai_def_agent
#   6. Cleans up the temporary staging directory
#
# This avoids copying lib/ into each agent's source tree. You only ever
# edit lib/ in one place.
#
# Prerequisites:
#   uv and bedrock-agentcore-starter-toolkit (run through uv)
#   aws configure (or set AWS_PROFILE)
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ai-team-agentcore.XXXXXX")"

AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_DEFAULT_REGION

ALL_AGENTS=("ai-gk" "ai-def" "ai-mid" "ai-fwd1" "ai-fwd2")

# If an agent name was passed as argument, deploy only that one
if [ -n "$1" ]; then
  AGENTS=("$1")
else
  AGENTS=("${ALL_AGENTS[@]}")
fi

echo "=========================================="
echo "  AI Team — Deploy Agents"
echo "=========================================="
echo ""

# ------ Pre-flight ------
echo "Checking prerequisites..."

if ! command -v uv &> /dev/null; then
  echo "ERROR: 'uv' not found (required to run the standalone AgentCore toolkit)."
  exit 1
fi
echo "  uv: OK"

if ! command -v rsync &> /dev/null; then
  echo "ERROR: 'rsync' not found (needed to copy lib without __pycache__)."
  exit 1
fi
echo "  rsync: OK"

if ! command -v aws &> /dev/null; then
  echo "ERROR: 'aws' CLI not found."
  exit 1
fi
echo "  aws CLI: OK"

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
  echo "ERROR: No valid AWS credentials."
  exit 1
}
export AWS_ACCOUNT_ID
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  AWS Region:  $AWS_DEFAULT_REGION"
echo ""

GATEWAY_URL=""
for agent in "${AGENTS[@]}"; do
  if [[ "$agent" == "ai-def" ]]; then
    GATEWAY_URL=$(aws cloudformation describe-stacks \
      --stack-name AgentCore-TeamStrandsBalanced-default \
      --query "Stacks[0].Outputs[?OutputKey=='GatewayTacticalToolsUrlOutput'].OutputValue | [0]" \
      --output text)
    if [[ -z "$GATEWAY_URL" || "$GATEWAY_URL" == "None" ]]; then
      echo "ERROR: tactical-tools gateway URL not found; deploy the gateway first."
      exit 1
    fi
    break
  fi
done

# ------ Cleanup on exit ------
cleanup() {
  echo ""
  echo "Cleaning up build directory..."
  rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

# ------ Build & deploy each agent ------
DEPLOYED=()
FAILED=()

for agent in "${AGENTS[@]}"; do
  AGENT_SRC="$SCRIPT_DIR/$agent"
  STAGE="$BUILD_DIR/$agent"

  echo "=========================================="
  echo "  Deploying: $agent"
  echo "=========================================="

  # Validate agent directory exists
  if [ ! -d "$AGENT_SRC" ]; then
    echo "  ERROR: Agent directory not found: $AGENT_SRC"
    FAILED+=("$agent")
    continue
  fi

  # Assemble staging directory
  rm -rf "$STAGE"
  mkdir -p "$STAGE/src"

  # Copy agent source
  cp "$AGENT_SRC/src/main.py" "$STAGE/src/main.py"

  # Copy shared lib (the whole point — single source of truth)
  # Use rsync to exclude __pycache__
  rsync -a --exclude='__pycache__' "$SCRIPT_DIR/../lib/" "$STAGE/lib/"

  # Copy requirements.txt
  cp "$AGENT_SRC/requirements.txt" "$STAGE/requirements.txt"

  # Generate .bedrock_agentcore.yaml from template
  sed \
    -e "s|\${AWS_ACCOUNT_ID}|$AWS_ACCOUNT_ID|g" \
    -e "s|\${AWS_DEFAULT_REGION}|$AWS_DEFAULT_REGION|g" \
    "$AGENT_SRC/.bedrock_agentcore.yaml.template" > "$STAGE/.bedrock_agentcore.yaml"

  # Deploy from staging directory
  echo "  Deploying from: $STAGE"
  if [[ "$agent" == "ai-def" ]]; then
    if (
      cd "$STAGE" &&
      uv run --python 3.12 --with bedrock-agentcore-starter-toolkit \
        agentcore deploy --auto-update-on-conflict \
        --env "AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL=$GATEWAY_URL"
    ); then
      echo "  ✅ $agent: DEPLOYED with tactical-tools gateway"
      DEPLOYED+=("$agent")
    else
      echo "  ❌ $agent: FAILED"
      FAILED+=("$agent")
    fi
  elif (
    cd "$STAGE" &&
    uv run --python 3.12 --with bedrock-agentcore-starter-toolkit \
      agentcore deploy --auto-update-on-conflict
  ); then
    echo "  ✅ $agent: DEPLOYED"
    DEPLOYED+=("$agent")
  else
    echo "  ❌ $agent: FAILED"
    FAILED+=("$agent")
  fi
  echo ""
done

# ------ Summary ------
echo "=========================================="
echo "  Deployment Summary"
echo "=========================================="
echo ""
echo "  Deployed: ${DEPLOYED[*]:-none}"
echo "  Failed:   ${FAILED[*]:-none}"
echo "  Account:  $AWS_ACCOUNT_ID"
echo "  Region:   $AWS_DEFAULT_REGION"
echo ""

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "Some agents failed to deploy. Check the output above."
  exit 1
fi

echo "All agents deployed successfully."
