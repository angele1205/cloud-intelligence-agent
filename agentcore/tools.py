# CostOp Intelligence Agent - Tools
# Created by amitml (https://github.com/amitml)
"""
CostOp Tools - Refactored (12 combined tools from 36)
"""
import boto3
import json
import time
import os
from datetime import datetime, timezone, timedelta
from strands import tool

# Clients
cw = boto3.client('cloudwatch')
ct = boto3.client('cloudtrail')
logs_client = boto3.client('logs')
ce_client = boto3.client('ce')
ddb = boto3.resource('dynamodb')

# Table names from environment
PATTERNS_TABLE = os.environ.get('PATTERNS_TABLE', 'cost_patterns')
INVESTIGATIONS_TABLE = os.environ.get('INVESTIGATIONS_TABLE', 'cost_investigations')
TOPOLOGY_TABLE = os.environ.get('TOPOLOGY_TABLE', 'cost_topology')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')


# ============================================================
# 1. GET_RESOURCE_INFO - Infrastructure discovery (replaces 10 tools)
# ============================================================

@tool
def get_resource_info(resource_type: str, resource_id: str = '') -> str:
    """Get configuration/details for any AWS resource. Use to trace callers, verify ownership, check topology.
    resource_type:
      'agent_runtime' - AgentCore runtime config (model, env vars). Pass runtime_id or empty to list all.
      'lambda' - Lambda function config (env vars, role, timeout). Pass function name.
      'stack' - CloudFormation stack resources. Pass stack name.
      'eventbridge' - EventBridge rule targets. Pass rule name.
      'iam_role' - IAM role details + tags. Pass role name.
      'tags' - Resource tags (Owner, Team). Pass resource ARN.
      'sns_topic' - SNS subscribers. Pass topic ARN.
      'ecs' - ECS services. Pass cluster name or empty to list clusters.
      'stepfunctions' - Step Function executions. Pass state machine ARN or empty to list.
      'bedrock_logging' - Check if invocation logging is enabled. No resource_id needed.
    resource_id: name, ARN, or ID (empty = list/discover)"""
    try:
        if resource_type == 'agent_runtime':
            client = boto3.client('bedrock-agentcore-control')
            if not resource_id:
                resp = client.list_agent_runtimes()
                return json.dumps([{'id': r['agentRuntimeId'], 'name': r.get('agentRuntimeName', ''), 'status': r['status']} for r in resp.get('agentRuntimes', [])[:10]])
            resp = client.get_agent_runtime(agentRuntimeId=resource_id)
            return json.dumps({'name': resp.get('agentRuntimeName'), 'status': resp.get('status'), 'env_vars': {k: v[:60] for k, v in resp.get('environmentVariables', {}).items()}, 'container': resp.get('agentRuntimeArtifact', {}).get('containerConfiguration', {}).get('containerUri', ''), 'role': resp.get('roleArn', '')})
        elif resource_type == 'lambda':
            resp = boto3.client('lambda').get_function_configuration(FunctionName=resource_id)
            return json.dumps({'name': resp['FunctionName'], 'runtime': resp.get('Runtime', ''), 'role': resp.get('Role', ''), 'timeout': resp.get('Timeout'), 'memory': resp.get('MemorySize'), 'env_vars': {k: v[:80] for k, v in resp.get('Environment', {}).get('Variables', {}).items()}, 'last_modified': resp.get('LastModified', '')})
        elif resource_type == 'stack':
            resp = boto3.client('cloudformation').list_stack_resources(StackName=resource_id)
            return json.dumps([{'type': r['ResourceType'], 'logical': r['LogicalResourceId'], 'physical': r.get('PhysicalResourceId', '')[:80]} for r in resp.get('StackResourceSummaries', [])[:20]])
        elif resource_type == 'eventbridge':
            resp = boto3.client('events').list_targets_by_rule(Rule=resource_id)
            return json.dumps([{'id': t['Id'], 'arn': t['Arn']} for t in resp.get('Targets', [])])
        elif resource_type == 'iam_role':
            role = boto3.client('iam').get_role(RoleName=resource_id)['Role']
            tags = {t['Key']: t['Value'] for t in role.get('Tags', [])}
            return json.dumps({'arn': role['Arn'], 'created': str(role['CreateDate']), 'trust': str(role.get('AssumeRolePolicyDocument', {}).get('Statement', [{}])[0].get('Principal', ''))[:150], 'tags': tags})
        elif resource_type == 'tags':
            resp = boto3.client('resourcegroupstaggingapi').get_resources(ResourceARNList=[resource_id])
            for r in resp.get('ResourceTagMappingList', []):
                return json.dumps({t['Key']: t['Value'] for t in r.get('Tags', [])})
            return "No tags found."
        elif resource_type == 'sns_topic':
            resp = boto3.client('sns').list_subscriptions_by_topic(TopicArn=resource_id)
            return json.dumps([{'protocol': s['Protocol'], 'endpoint': s['Endpoint']} for s in resp.get('Subscriptions', [])])
        elif resource_type == 'ecs':
            client = boto3.client('ecs')
            if not resource_id:
                return json.dumps([c.split('/')[-1] for c in client.list_clusters().get('clusterArns', [])])
            services = client.list_services(cluster=resource_id).get('serviceArns', [])
            if services:
                details = client.describe_services(cluster=resource_id, services=services[:5])
                return json.dumps([{'name': s['serviceName'], 'running': s['runningCount']} for s in details.get('services', [])])
            return "No services."
        elif resource_type == 'stepfunctions':
            client = boto3.client('stepfunctions')
            if not resource_id:
                return json.dumps([{'name': m['name'], 'arn': m['stateMachineArn']} for m in client.list_state_machines(maxResults=10).get('stateMachines', [])])
            return json.dumps([{'name': e['name'], 'status': e['status'], 'start': str(e['startDate'])} for e in client.list_executions(stateMachineArn=resource_id, maxResults=10).get('executions', [])])
        elif resource_type == 'bedrock_logging':
            resp = boto3.client('bedrock').get_model_invocation_logging_configuration()
            config = resp.get('loggingConfig', {})
            if not config:
                return "Invocation logging NOT configured."
            return json.dumps({'enabled': True, 'log_group': config.get('cloudWatchConfig', {}).get('logGroupName', ''), 'text_delivery': config.get('textDataDeliveryEnabled', False)})
        else:
            return f"Unknown resource_type '{resource_type}'. Valid: agent_runtime, lambda, stack, eventbridge, iam_role, tags, sns_topic, ecs, stepfunctions, bedrock_logging"
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# 2. GET_MONITORING_DATA - Metrics, alarms, usage (replaces 5 tools)
# ============================================================

@tool
def get_monitoring_data(query_type: str, target: str = '', hours: int = 6) -> str:
    """Get monitoring metrics, alarm status, or usage data.
    query_type:
      'alarms' - CloudWatch alarm status. Pass alarm name in target or empty for all CostAgent alarms.
      'alarm_history' - When alarm fired/resolved. Pass alarm name in target.
      'metric' - Hourly metric trend. Pass 'Namespace/MetricName' in target (e.g. 'AWS/Bedrock/InputTokenCount').
      'bedrock_usage' - Real-time Bedrock token counts (last 60 min). No target needed.
      'lambda_invocations' - Lambda invocation count. Pass function name in target.
    hours: time window (default 6)"""
    try:
        if query_type == 'alarms':
            if target:
                resp = cw.describe_alarms(AlarmNames=[target])
            else:
                resp = cw.describe_alarms(AlarmNamePrefix='CostAgent', MaxRecords=20)
            return json.dumps([{'name': a['AlarmName'], 'state': a['StateValue'], 'metric': f"{a['Namespace']}/{a['MetricName']}", 'threshold': a.get('Threshold'), 'dimensions': [f"{d['Name']}={d['Value']}" for d in a.get('Dimensions', [])], 'reason': a.get('StateReason', '')[:150]} for a in resp.get('MetricAlarms', [])], default=str)
        elif query_type == 'alarm_history':
            start = datetime.now(timezone.utc) - timedelta(days=7)
            resp = cw.describe_alarm_history(AlarmName=target, HistoryItemType='StateUpdate', StartDate=start, MaxRecords=20)
            return json.dumps([{'time': h['Timestamp'].strftime('%Y-%m-%d %H:%M'), 'summary': h.get('HistorySummary', '')[:100]} for h in resp.get('AlarmHistoryItems', [])]) or "No history."
        elif query_type == 'metric':
            parts = target.split('/')
            namespace = '/'.join(parts[:-1]) if len(parts) > 1 else 'AWS/Bedrock'
            metric_name = parts[-1]
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=hours)
            resp = cw.get_metric_data(MetricDataQueries=[{'Id': 'm1', 'MetricStat': {'Metric': {'Namespace': namespace, 'MetricName': metric_name}, 'Period': 3600, 'Stat': 'Sum'}, 'ReturnData': True}], StartTime=start, EndTime=end)
            results = resp.get('MetricDataResults', [])
            if results and results[0].get('Values'):
                data = [{'time': t.strftime('%H:%M'), 'value': int(v)} for t, v in zip(results[0]['Timestamps'], results[0]['Values'])]
                return json.dumps(sorted(data, key=lambda x: x['time']))
            return "No data."
        elif query_type == 'bedrock_usage':
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=60)
            metrics = ['InputTokenCount', 'OutputTokenCount', 'Invocations', 'InvocationThrottles']
            queries = [{'Id': f'm{i}', 'MetricStat': {'Metric': {'Namespace': 'AWS/Bedrock', 'MetricName': m}, 'Period': 300, 'Stat': 'Sum'}, 'ReturnData': True} for i, m in enumerate(metrics)]
            resp = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
            summary = {}
            for i, m in enumerate(metrics):
                values = resp['MetricDataResults'][i].get('Values', [])
                summary[m] = int(sum(values)) if values else 0
            summary['estimated_cost_usd'] = round((summary['InputTokenCount'] * 0.003 + summary['OutputTokenCount'] * 0.015) / 1000, 4)
            return json.dumps(summary)
        elif query_type == 'lambda_invocations':
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=hours)
            resp = cw.get_metric_data(MetricDataQueries=[
                {'Id': 'inv', 'MetricStat': {'Metric': {'Namespace': 'AWS/Lambda', 'MetricName': 'Invocations', 'Dimensions': [{'Name': 'FunctionName', 'Value': target}]}, 'Period': 3600, 'Stat': 'Sum'}, 'ReturnData': True}
            ], StartTime=start, EndTime=end)
            values = resp['MetricDataResults'][0].get('Values', [])
            return json.dumps({'function': target, 'total': int(sum(values)), 'hourly': [int(v) for v in values]})
        else:
            return f"Unknown query_type '{query_type}'. Valid: alarms, alarm_history, metric, bedrock_usage, lambda_invocations"
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# 3. GET_COST_DATA - Cost Explorer queries (replaces 5 tools)
# ============================================================

@tool
def get_cost_data(query_type: str, days: int = 7, service: str = '', tag_key: str = '') -> str:
    """Get cost and billing data.
    query_type:
      'usage' - Cost by service. Pass service filter (e.g. 'Amazon Bedrock') or empty for all.
      'anomalies' - Cost anomalies detected by AWS.
      'forecast' - Projected spend for next month.
      'budgets' - Budget status and limits.
      'by_tag' - Cost grouped by tag. Pass tag_key (e.g. 'Team', 'Project').
    days: lookback period (default 7)"""
    try:
        end = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        if query_type == 'usage':
            kwargs = {'TimePeriod': {'Start': start, 'End': end}, 'Granularity': 'DAILY', 'Metrics': ['BlendedCost'], 'GroupBy': [{'Type': 'DIMENSION', 'Key': 'SERVICE'}]}
            if service:
                kwargs['Filter'] = {'Dimensions': {'Key': 'SERVICE', 'Values': [service]}}
            resp = ce_client.get_cost_and_usage(**kwargs)
            results = []
            for period in resp.get('ResultsByTime', []):
                for group in period.get('Groups', []):
                    cost = float(group['Metrics']['BlendedCost']['Amount'])
                    if cost > 0.01:
                        results.append({'date': period['TimePeriod']['Start'], 'service': group['Keys'][0], 'cost': round(cost, 2)})
            return json.dumps(sorted(results, key=lambda x: -x['cost'])[:20]) or "No cost data."
        elif query_type == 'anomalies':
            resp = ce_client.get_anomalies(DateInterval={'StartDate': start, 'EndDate': end}, MaxResults=10)
            return json.dumps([{'start': a.get('AnomalyStartDate', ''), 'impact': a.get('Impact', {}).get('TotalImpact', 0), 'service': (a.get('RootCauses', [{}])[0].get('Service', 'Unknown'))} for a in resp.get('Anomalies', [])]) or "No anomalies."
        elif query_type == 'forecast':
            start_f = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            end_f = (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%d')
            resp = ce_client.get_cost_forecast(TimePeriod={'Start': start_f, 'End': end_f}, Metric='BLENDED_COST', Granularity='MONTHLY')
            return json.dumps({'total_forecast': round(float(resp.get('Total', {}).get('Amount', '0')), 2)})
        elif query_type == 'budgets':
            account_id = boto3.client('sts').get_caller_identity()['Account']
            resp = boto3.client('budgets').describe_budgets(AccountId=account_id, MaxResults=10)
            return json.dumps([{'name': b['BudgetName'], 'limit': f"${b['BudgetLimit']['Amount']}", 'actual': f"${b.get('CalculatedSpend', {}).get('ActualSpend', {}).get('Amount', '0')}"} for b in resp.get('Budgets', [])]) or "No budgets."
        elif query_type == 'by_tag':
            resp = ce_client.get_cost_and_usage(TimePeriod={'Start': start, 'End': end}, Granularity='DAILY', Metrics=['BlendedCost'], GroupBy=[{'Type': 'TAG', 'Key': tag_key}])
            results = {}
            for period in resp.get('ResultsByTime', []):
                for group in period.get('Groups', []):
                    key = group['Keys'][0].replace(f'{tag_key}$', '') or 'untagged'
                    results[key] = results.get(key, 0) + float(group['Metrics']['BlendedCost']['Amount'])
            return json.dumps({k: round(v, 2) for k, v in sorted(results.items(), key=lambda x: -x[1]) if v > 0.01})
        else:
            return f"Unknown query_type. Valid: usage, anomalies, forecast, budgets, by_tag"
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# 4. GET_RECENT_CHANGES - CloudTrail (absorbs deployments + config changes)
# ============================================================

@tool
def get_recent_changes(service_name: str, hours: int = 6, change_type: str = 'all') -> str:
    """Get recent API changes from CloudTrail. Returns summary of write operations + caller details.
    service_name: 'bedrock', 'lambda', 'ec2', 'ecs', etc.
    change_type: 'all' | 'deployments' (code deploys only) | 'config' (config changes only)"""
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    sources = [f'{service_name}.amazonaws.com']
    if service_name == 'bedrock':
        sources = ['bedrock.amazonaws.com', 'bedrock-runtime.amazonaws.com', 'bedrock-agentcore.amazonaws.com']
    deploy_events = ['UpdateFunctionCode', 'UpdateFunctionConfiguration', 'CreateFunction', 'CreateDeployment', 'UpdateService', 'RegisterTaskDefinition', 'PutImage', 'UpdateAgent', 'CreateAgentVersion', 'UpdateAgentRuntime']
    events = []
    for source in sources:
        response = ct.lookup_events(LookupAttributes=[{'AttributeKey': 'EventSource', 'AttributeValue': source}], StartTime=start, MaxResults=15)
        for e in response.get('Events', []):
            event_data = {'time': e['EventTime'].strftime('%H:%M'), 'event': e['EventName'], 'user': e.get('Username', 'unknown')}
            if e.get('CloudTrailEvent'):
                try:
                    ct_event = json.loads(e['CloudTrailEvent'])
                    params = ct_event.get('requestParameters', {})
                    if params:
                        event_data['parameters'] = {k: str(v)[:100] for k, v in list(params.items())[:5] if k != 'payload'}
                    event_data['caller_arn'] = ct_event.get('userIdentity', {}).get('arn', '')
                    event_data['source_ip'] = ct_event.get('sourceIPAddress', '')
                    event_data['user_agent'] = ct_event.get('userAgent', '')[:60]
                except: pass
            events.append(event_data)
    events.sort(key=lambda x: x['time'], reverse=True)
    if change_type == 'deployments':
        events = [e for e in events if e['event'] in deploy_events]
    elif change_type == 'config':
        events = [e for e in events if not e['event'].startswith(('Get', 'Describe', 'List', 'Lookup'))]
    if not events:
        return f"No changes found for {service_name} in last {hours}h."
    output = events[:10]
    result = json.dumps(output, default=str)
    if len(result) > 4000:
        for e in output:
            if 'parameters' in e:
                e['parameters'] = {k: str(v)[:80] for k, v in list(e['parameters'].items())[:3]}
        result = json.dumps(output, default=str)
    return result


# ============================================================
# 5. CHECK_INVOCATION_LOGS - Bedrock call details (keep separate - complex)
# ============================================================

@tool
def check_invocation_logs(hours: int = 1, detail: str = 'summary') -> str:
    """Check Bedrock model invocation logs. Returns smart summary + outliers.
    hours: time window
    detail: 'summary' (aggregated stats + top callers + outliers) | 'full' (raw rows) | 'caller:ID' (filter by caller)"""
    start = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
    end = int(datetime.now(timezone.utc).timestamp())
    if detail.startswith('caller:'):
        caller_filter = detail.split(':', 1)[1]
        query = f"fields @timestamp, modelId, input.inputTokenCount as inputTokens, output.outputTokenCount as outputTokens, identity.arn as callerArn, operation as apiOperation | filter identity.arn like '{caller_filter}' | sort @timestamp desc | limit 15"
    else:
        query = "fields @timestamp, modelId, input.inputTokenCount as inputTokens, output.outputTokenCount as outputTokens, identity.arn as callerArn, operation as apiOperation | sort @timestamp desc | limit 30"
    try:
        response = logs_client.start_query(logGroupName='/aws/bedrock/modelinvocations', startTime=start, endTime=end, queryString=query)
        query_id = response['queryId']
        for _ in range(30):
            result = logs_client.get_query_results(queryId=query_id)
            if result['status'] == 'Complete': break
            time.sleep(1)
        entries = []
        for row in result.get('results', []):
            fields_data = {f['field']: f['value'] for f in row}
            caller = fields_data.get('callerArn', 'unknown')
            entries.append({'time': fields_data.get('@timestamp', ''), 'model': fields_data.get('modelId', ''), 'api': fields_data.get('apiOperation', 'Converse'), 'input_tokens': int(float(fields_data.get('inputTokens', '0'))), 'output_tokens': int(float(fields_data.get('outputTokens', '0'))), 'caller_role': caller.split('/')[-1] if '/' in caller else caller, 'caller_arn': caller})
        if not entries: return "No invocation logs found."
        if detail == 'full': return json.dumps(entries[:15])
        # Summary
        total_input = sum(e['input_tokens'] for e in entries)
        total_output = sum(e['output_tokens'] for e in entries)
        total_calls = len(entries)
        avg_input = total_input // total_calls if total_calls else 0
        cost = (total_input * 0.003 + total_output * 0.015) / 1000
        callers = {}
        for e in entries:
            c = e['caller_role']
            if c not in callers: callers[c] = {'calls': 0, 'input': 0}
            callers[c]['calls'] += 1; callers[c]['input'] += e['input_tokens']
        outliers = sorted(entries, key=lambda x: -x['input_tokens'])[:7]
        summary = f"INVOCATIONS ({hours}h): {total_calls} calls | {total_input:,} in / {total_output:,} out | ${cost:.2f}\nAvg: {avg_input:,} tokens/call\n\nCALLERS:\n"
        for c, data in sorted(callers.items(), key=lambda x: -x[1]['input'])[:6]:
            summary += f"  {c}: {data['input']:,} in ({data['input']*100//total_input if total_input else 0}%) | {data['calls']} calls\n"
        summary += "\nTOP CALLS:\n"
        for o in outliers:
            summary += f"  {o['time'][:19]} | {o['input_tokens']:,} in | {o['caller_role']}\n"
        return summary
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# 6. MANAGE_PATTERNS - Pattern memory + topology (replaces 4 tools)
# ============================================================

@tool
def manage_patterns(action: str, pattern_type: str = '', data: str = '') -> str:
    """Manage cost patterns and topology for learning.
    action:
      'find' - Search for similar past patterns. Pass pattern_type (e.g. 'bedrock-token-spike').
      'save' - Save new pattern. Pass pattern_type + data as JSON with root_cause, resolution, cost_impact.
      'topology' - Check resource connections. Pass resource name in pattern_type.
      'save_investigation' - Save investigation result. Pass data as JSON with alarm_name, severity, summary, findings, timeline, actions.
    """
    try:
        if action == 'find':
            table = ddb.Table(PATTERNS_TABLE)
            resp = table.scan(FilterExpression='pattern_type = :pt', ExpressionAttributeValues={':pt': pattern_type})
            items = resp.get('Items', [])
            return json.dumps(items, default=str) if items else "No similar patterns found. This is new."
        elif action == 'save':
            import uuid
            table = ddb.Table(PATTERNS_TABLE)
            info = json.loads(data) if data else {}
            table.put_item(Item={'pattern_id': str(uuid.uuid4()), 'pattern_type': pattern_type, 'root_cause': info.get('root_cause', ''), 'resolution': info.get('resolution', ''), 'cost_impact': info.get('cost_impact', ''), 'timestamp': datetime.now(timezone.utc).isoformat()})
            return f"Pattern saved: {pattern_type}"
        elif action == 'topology':
            table = ddb.Table(TOPOLOGY_TABLE)
            resp = table.scan()
            matches = [item for item in resp.get('Items', []) if pattern_type.lower() in item.get('resource_id', '').lower() or pattern_type.lower() in item.get('name', '').lower()]
            if matches: return json.dumps(matches[:5], default=str)
            return f"No topology entry for '{pattern_type}'. Cannot confirm connection — do NOT claim correlation."
        elif action == 'save_investigation':
            import uuid
            table = ddb.Table(INVESTIGATIONS_TABLE)
            info = json.loads(data) if data else {}
            table.put_item(Item={'investigation_id': str(uuid.uuid4()), 'alarm_name': info.get('alarm_name', ''), 'severity': info.get('severity', 'info'), 'summary': info.get('summary', ''), 'findings': info.get('findings', '[]'), 'timeline': info.get('timeline', '[]'), 'actions': info.get('actions', '[]'), 'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'completed'})
            return "Investigation saved."
        else:
            return "Unknown action. Valid: find, save, topology, save_investigation"
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# 7. DETECT_ISSUES - Loop detection, agent costs, quotas (replaces 3 tools)
# ============================================================

@tool
def detect_issues(check_type: str, hours: int = 24) -> str:
    """Detect cost issues and check limits.
    check_type:
      'loops' - Detect runaway agent loops (>50 calls in 5 min window).
      'agent_costs' - Per-agent token breakdown and costs.
      'quotas' - Service quota limits. Pass search term in hours param (ignored, use check_type='quotas:search_term').
    hours: time window (default 24, ignored for quotas)"""
    try:
        if check_type == 'loops':
            start = int((datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp())
            end = int(datetime.now(timezone.utc).timestamp())
            query = "fields @timestamp, modelId, input.inputTokenCount | stats count(*) as calls, sum(input.inputTokenCount) as tokens by bin(5m) as time_bucket, coalesce(requestMetadata.agentId, 'direct') as agent_id | filter calls > 50 | sort calls desc"
            response = logs_client.start_query(logGroupName='/aws/bedrock/modelinvocations', startTime=start, endTime=end, queryString=query)
            query_id = response['queryId']
            for _ in range(30):
                result = logs_client.get_query_results(queryId=query_id)
                if result['status'] == 'Complete': break
                time.sleep(1)
            if result.get('results'):
                alerts = [{'agent_id': {f['field']: f['value'] for f in row}.get('agent_id'), 'calls': int({f['field']: f['value'] for f in row}.get('calls', 0))} for row in result['results']]
                return json.dumps({'status': 'POTENTIAL_LOOPS', 'alerts': alerts})
            return json.dumps({'status': 'OK', 'message': 'No abnormal patterns.'})
        elif check_type == 'agent_costs':
            start = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
            end = int(datetime.now(timezone.utc).timestamp())
            query = "fields @timestamp, modelId, input.inputTokenCount, output.outputTokenCount | stats sum(input.inputTokenCount) as input_tokens, sum(output.outputTokenCount) as output_tokens, count(*) as invocations by coalesce(requestMetadata.agentId, 'direct-invoke') as agent_id | sort input_tokens desc"
            response = logs_client.start_query(logGroupName='/aws/bedrock/modelinvocations', startTime=start, endTime=end, queryString=query)
            query_id = response['queryId']
            for _ in range(30):
                result = logs_client.get_query_results(queryId=query_id)
                if result['status'] == 'Complete': break
                time.sleep(1)
            agents = []
            for row in result.get('results', []):
                fields = {f['field']: f['value'] for f in row}
                inp = int(fields.get('input_tokens', 0)); out = int(fields.get('output_tokens', 0))
                agents.append({'agent_id': fields.get('agent_id', ''), 'invocations': int(fields.get('invocations', 0)), 'input_tokens': inp, 'output_tokens': out, 'cost_usd': round((inp * 0.003 + out * 0.015) / 1000, 4)})
            return json.dumps(agents) if agents else "No data."
        elif check_type.startswith('quotas'):
            search = check_type.split(':')[1] if ':' in check_type else 'token'
            sq = boto3.client('service-quotas')
            all_quotas = []
            next_token = None
            for _ in range(5):  # max 5 pages
                kwargs = {'ServiceCode': 'bedrock', 'MaxResults': 100}
                if next_token:
                    kwargs['NextToken'] = next_token
                resp = sq.list_service_quotas(**kwargs)
                all_quotas.extend(resp.get('Quotas', []))
                next_token = resp.get('NextToken')
                if not next_token:
                    break
            results = [{'name': q['QuotaName'], 'value': q['Value'], 'code': q['QuotaCode']} for q in all_quotas if search.lower() in q.get('QuotaName', '').lower()]
            return json.dumps(results[:15]) if results else f"No quotas matching '{search}' in {len(all_quotas)} total quotas. Try: 'Claude', 'Sonnet', 'Haiku', 'cross-region'."
        else:
            return "Unknown check_type. Valid: loops, agent_costs, quotas:search_term"
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# 8-12. ACTION TOOLS (keep separate - destructive, need confirmation)
# ============================================================

@tool
def send_notification(subject: str, message: str) -> str:
    """Send alert notification via SNS. Use for urgent findings needing human attention."""
    try:
        sns_client = boto3.client('sns')
        if not SNS_TOPIC_ARN: return "SNS topic not configured."
        sns_client.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)
        return f"Notification sent: {subject}"
    except Exception as e:
        return f"Failed: {str(e)}"

@tool
def stop_agent_invocations(function_name: str, max_concurrency: int = 0) -> str:
    """Throttle/stop a Lambda function driving excessive costs. DESTRUCTIVE - confirm first.
    max_concurrency: 0=stop completely, low number=throttle."""
    try:
        boto3.client('lambda').put_function_concurrency(FunctionName=function_name, ReservedConcurrentExecutions=max_concurrency)
        return f"Lambda '{function_name}' {'stopped' if max_concurrency == 0 else f'throttled to {max_concurrency}'}."
    except Exception as e:
        return f"Failed: {str(e)}"

@tool
def set_budget_alert(monthly_limit: int, alert_threshold: int = 80) -> str:
    """Create AWS Budget for Bedrock. DESTRUCTIVE - confirm first."""
    try:
        account_id = boto3.client('sts').get_caller_identity()['Account']
        boto3.client('budgets').create_budget(AccountId=account_id, Budget={'BudgetName': 'CostOp-Bedrock-Budget', 'BudgetLimit': {'Amount': str(monthly_limit), 'Unit': 'USD'}, 'TimeUnit': 'MONTHLY', 'BudgetType': 'COST', 'CostFilters': {'Service': ['Amazon Bedrock']}}, NotificationsWithSubscribers=[{'Notification': {'NotificationType': 'ACTUAL', 'ComparisonOperator': 'GREATER_THAN', 'Threshold': alert_threshold, 'ThresholdType': 'PERCENTAGE'}, 'Subscribers': [{'SubscriptionType': 'SNS', 'Address': SNS_TOPIC_ARN}]}])
        return f"Budget created: ${monthly_limit}/month, alert at {alert_threshold}%."
    except Exception as e:
        return f"Failed: {str(e)}"

@tool
def request_quota_increase(service_code: str, quota_code: str, desired_value: int) -> str:
    """Request service quota increase. DESTRUCTIVE - confirm first."""
    try:
        resp = boto3.client('service-quotas').request_service_quota_increase(ServiceCode=service_code, QuotaCode=quota_code, DesiredValue=float(desired_value))
        return f"Quota increase requested: {service_code}/{quota_code} → {desired_value}. Status: PENDING."
    except Exception as e:
        return f"Failed: {str(e)}"

@tool
def create_support_case(subject: str, description: str, severity: str = 'low') -> str:
    """Create AWS Support case. DESTRUCTIVE - confirm first."""
    try:
        resp = boto3.client('support', region_name='us-east-1').create_case(subject=subject, communicationBody=description, severityCode=severity, categoryCode='other', serviceCode='general-info', issueType='technical')
        return f"Support case created: {resp.get('caseId', 'unknown')}."
    except Exception as e:
        return f"Failed: {str(e)}"
