### lambda_function.py

import openai
import json
import re
import os
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import boto3
from botocore.exceptions import ClientError


def get_secret():
    secret_name = os.environ["ENV_SECRET_NAME"]
    region_name = os.environ["ENV_REGION_NAME"]
    
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e
    
    #####print("secret dir",get_secret_value_response['SecretString'])
    # Decrypts secret using the associated KMS key.
    secret = get_secret_value_response['SecretString']
    
    # Your code goes here.
    return secret


def lambda_handler(event, context):
    print("event: ", event)
    if "X-Slack-Retry-Num" in event["headers"]:
        return {"statusCode": 200, "body": json.dumps({"message": "No need to resend"})}
    
    
    # Get secrets from Secrets-Manager
    secret_dict = json.loads(get_secret())
    
    # initializer
    slack_client = WebClient(secret_dict["SLACK_OAUTH_TOKEN"])
    openai.organization = secret_dict["OPENAI_ORGANIZATION"]
    openai.api_key = secret_dict["OPENAI_API_KEY"]
    manabitCoinAddress = secret_dict["EOA_SST_FUND"] #default EoA
    
    body = json.loads(event["body"])
    text = re.sub(r"<@.*>", "", body["event"]["text"])
    channel = body["event"]["channel"]
    thread_ts = body["event"].get("thread_ts") or body["event"]["ts"]
    print("input: ", text, "channel: ", channel, "thread:", thread_ts)
    
    
    
    # get thread messages
    thread_messages_response = slack_client.conversations_replies(channel=channel, ts=thread_ts)
    messages = thread_messages_response["messages"]
    messages.sort(key=lambda x: float(x["ts"]))
    #print("messages:",messages)
    
    
    
    # get recent 30 messages in the thread
    prev_messages = [
        {
            "role": "assistant" if "bot_id" in m and m["bot_id"] else "user",
            "content": re.sub(r"<@.*>|`info: prompt.*USD\)` ", "", m["text"]),
        }
        for m in messages[0:][-30:]
    ]
    print("prev_messages:",prev_messages)
    
    # pull out manabitCoinAddress
    msg = prev_messages[0]['content']
    pattern = r'まなびっとコインアドレス:\n(0x[0-9a-fA-F]{40})'
    match = re.search(pattern, msg)
    if match:
        manabitCoinAddress = match.group(1)
        print("manabitCoinAddress:",manabitCoinAddress)
    pattern = r'まなびっとコインアドレス:\s(0x[0-9a-fA-F]*)'
    msg_modified = re.sub(pattern, '', msg)
    prev_messages[0]['content'] = msg_modified
    print("prev_messages(modified):",prev_messages)
    
    
    # make responce with system_prompt from base-model
    with open(os.environ["ENV_SYSTEM_PROMPT_BASE"], 'r') as file:
        system_prompt = file.read()
    # completion response
    completion_msg = make_response(prev_messages,system_prompt,slack_client, channel, thread_ts)
    
    
    ### extra: add socring in case of first response
    if len(prev_messages) == 1:
        with open(os.environ["ENV_SYSTEM_PROMPT_GACHA"], 'r') as file:
            system_prompt_gacha = file.read()
            
        # chack manabit
        msg = prev_messages[0]['content']
        print("msg:",msg)
        if "学習テーマ" in msg and \
            "日時" in msg and \
            "学習記録" in msg:
            
            # completion manabit GACHA
            completion_msg = make_response(prev_messages,system_prompt_gacha,slack_client, channel, thread_ts)
            starcount = completion_msg.count('★')
            print("star count:",starcount)
            
            # star
            if starcount == 0:
                print("nothing start count")
                return {"statusCode": 500}
            
            # address error
            if not manabitCoinAddress:
                print("undefined manabitCoinAddress")
                return {"statusCode": 500}
            
            
            
    
    
    
    
    
    
    
    return {"statusCode": 200}



def make_response(prev_msg,system_prompt,slack_client, channel, thread_ts):
    
    # create completion
    openai_response = create_completion(prev_msg,system_prompt)
    print("openaiResponse: ", openai_response)
    
    # calculate tokens
    tkn_pro = openai_response["usage"]["prompt_tokens"]
    tkn_com = openai_response["usage"]["completion_tokens"]
    tkn_tot = openai_response["usage"]["total_tokens"]
    cost = tkn_tot * 0.002 / 1000
    msg_head = "\n `info: prompt + completion = %s + %s = %s tokens(%.4f USD)` " % (tkn_pro,tkn_com,tkn_tot,cost)
    res_text = openai_response["choices"][0]["message"]["content"]
    ##answer = msg_head + res_text
    answer = res_text + msg_head
    print("answer:",answer)
    
    # post_message
    post_message(slack_client, channel, answer, thread_ts)
    
    return res_text



def create_completion(prev_msg,system_prompt):
    model="gpt-3.5-turbo"
    prompt=[
        {
            "role": "system",
            "content": system_prompt
        },
        *prev_msg
    ]
    print("mdoel:",model,"prompt:",prompt)
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=prompt
        )
        #print("openaiResponse: ", response)
        return response
    except Exception as err:
        print("Error: ", err)



def post_message(slack_client, channel, text, thread_ts):
    try:
        response = slack_client.chat_postMessage(
            channel=channel,
            text=text,
            as_user=True,
            thread_ts=thread_ts,
            reply_broadcast=False
        )
        print("slackResponse: ", response)
    except SlackApiError as e:
        print("Error posting message: {}".format(e))