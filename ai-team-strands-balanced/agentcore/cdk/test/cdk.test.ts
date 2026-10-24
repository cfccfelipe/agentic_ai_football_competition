import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { AgentCoreStack } from '../lib/cdk-stack';
import { AgentCoreMcp, type AgentCoreApplication, type AgentCoreMcpSpec } from '@aws/agentcore-cdk';

test('AgentCoreStack synthesizes with empty spec', () => {
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'TestStack', {
    spec: {
      name: 'testproject',
      version: 1,
      managedBy: 'CDK' as const,
      runtimes: [],
      memories: [],
      credentials: [],
      evaluators: [],
      onlineEvalConfigs: [],
      configBundles: [],
      policyEngines: [],
      payments: [],
      agentCoreGateways: [],
      mcpRuntimeTools: [],
      unassignedTargets: [],
      datasets: [],
      knowledgeBases: [],
    },
  });
  const template = Template.fromStack(stack);
  template.hasOutput('StackNameOutput', {
    Description: 'Name of the CloudFormation Stack',
  });
});

test('MCP gateway URL is wired to the application runtime using the expected env var', () => {
  const app = new cdk.App();
  const stack = new cdk.Stack(app, 'GatewayWiringTestStack', {
    env: { account: '123456789012', region: 'us-east-1' },
  });
  const addEnvironmentVariable = jest.fn();
  const application = {
    environments: new Map([
      [
        'ai_def_agent',
        {
          agent: { entrypoint: 'src/main.py', protocol: 'HTTP' },
          runtime: { addEnvironmentVariable },
        },
      ],
    ]),
    policyEngines: new Map(),
    knowledgeBases: new Map(),
  } as unknown as AgentCoreApplication;
  const mcpSpec: AgentCoreMcpSpec = {
    agentCoreGateways: [
      {
        name: 'tactical-tools',
        description: 'Tactical analysis tools',
        authorizerType: 'NONE',
        protocolType: 'MCP',
        enableSemanticSearch: false,
        exceptionLevel: 'NONE',
        targets: [],
      },
    ],
    mcpRuntimeTools: [],
  };

  new AgentCoreMcp(stack, 'Mcp', {
    projectName: 'TeamStrandsBalanced',
    mcpSpec,
    agentCoreApplication: application,
  });

  expect(addEnvironmentVariable).toHaveBeenCalledWith(
    'AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL',
    expect.any(String),
  );
  Template.fromStack(stack).resourceCountIs('AWS::BedrockAgentCore::Gateway', 1);
});
