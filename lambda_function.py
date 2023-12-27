### lambda_function.py
from __future__ import print_function

import json
import re
import os
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import openai

import hashlib


def lambda_handler(event, context):
    print("event: ", event)
    
    # prevent dual launch
    if "X-Slack-Retry-Num" in event["headers"]:
        return {"statusCode": 200, "body": json.dumps({"message": "No need to resend"})}
    
    ### initializer ####################################
    
    # Get secrets from Secrets-Manager
    secret_dict = json.loads(get_secret())
    slack_client = WebClient(secret_dict["SLACK_OAUTH_TOKEN"])
    openai.organization = secret_dict["OPENAI_ORGANIZATION"]
    openai.api_key = secret_dict["OPENAI_API_KEY"]
    manabitCoinAddress = secret_dict["EOA_SST_FUND"] #default EoA
    
    body = json.loads(event["body"])
    text = re.sub(r"<@.*>", "", body["event"]["text"])
    channel = body["event"]["channel"]
    thread_ts = body["event"].get("thread_ts") or body["event"]["ts"]
    userId = body["event"]["user"]
    print("input: ", text, "channel: ", channel, "thread:", thread_ts)
    
    
    
    ### preparation ####################################
    
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
    
    # prune string(address)
    msg = prev_messages[0]['content']
    pattern = r'まなびっとコインアドレス:\s(0x[0-9a-fA-F]*)'
    msg_modified = re.sub(pattern, '', msg)
    prev_messages[0]['content'] = msg_modified
    print("prev_messages(modified):",prev_messages)
    
    
    ### 1st: COMPLETION (bot conversation) ####################################
    
    # make responce with system_prompt from base-model
    with open(os.environ["ENV_SYSTEM_PROMPT_BASE"], 'r') as file:
        system_prompt = file.read()
    # completion response
    completion_msg = make_response(prev_messages,system_prompt)
    post_message(slack_client, channel, completion_msg, thread_ts)
    
    
    ### extra: add socring in case of first response
    if len(prev_messages) == 1:
        
        ### 2nd: COMPLETION (scoring for star) ####################################
        
        # check manabit
        if "学習テーマ" in text and \
            "日時" in text and \
            "学習記録" in text:
            
            # completion manabit GACHA
            with open(os.environ["ENV_SYSTEM_PROMPT_GACHA"], 'r') as file:
                system_prompt_gacha = file.read()
            completion_msg= make_response(prev_messages,system_prompt_gacha)
            post_message(slack_client, channel, completion_msg, thread_ts)
            
            starcount = completion_msg.count('★')
            print("star count:",starcount)
            
            # star
            if starcount == 0:
                print("nothing start count")
                return {"statusCode": 500}
            
            # manabitCoin address override to User's address
            pattern = r'まなびっとコインアドレス:\s(0x[0-9a-fA-F]{40})'
            match = re.search(pattern, text)
            if match:
                manabitCoinAddress = match.group(1)
                print("found manabitCoinAddress:",manabitCoinAddress)
            
        ### 3rd: WEB3 manabit contract  ##############################
            
        # send manabit
        web3_result = execute_WEB3_manabit(text,manabitCoinAddress,starcount)
        post_message(slack_client, channel, web3_result, thread_ts)
            
    return {"statusCode": 200}



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
    
    secret = get_secret_value_response['SecretString']
    
    # Your code goes here.
    return secret


def make_response(prev_msg,system_prompt):
    
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
    answer = res_text + msg_head
    print("answer:",answer)

    return res_text


def create_completion(prev_msg,system_prompt):
    model=os.environ["ENV_GPT_MODEL"]
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


def execute_WEB3_manabit(manabit,to_address,starcount):
    # gettime
    processingDate = datetime.today() + timedelta(hours=9)
    formattedDate = processingDate.strftime("%Y-%m-%d %H:%M:%S")
    
    # create manabit report & message digest
    ###manabit = userInfo["user"]["name"] + manabit
    print("manabit raw text:",manabit)
    manabitMD = hashlib.sha256(manabit.encode()).hexdigest()
    
    # create comment
    comment = {
        'date': formattedDate,
        'stars': starcount,
        'manabitHash': manabitMD
    }
    print("The your MANABIT MEMORY to be recorded in BlockChain: ",comment)
    
    # create web3 request
    _data = {
        "action": "sendManabit",
        "param": {
            "to_address": to_address,
            "amount": starcount,
            "comment": json.dumps(comment)
        }
    }
    
    web3_request = json.dumps(_data)
    print("WEB3---01: Payload",web3_request)
    ### lambda(web3.js) CALL START ###############################
    web3_client = boto3.client('lambda')
    web3_result = web3_client.invoke(
        FunctionName=os.environ["ENV_LAMBDA_INVOKE"],
        InvocationType='RequestResponse',
        Payload=web3_request
        
    )
    ### lambda(web3.js) CALL FINISH ##############################
    print("WEB3---02: response",web3_result)
    web3_res_payload = json.loads(web3_result['Payload'].read())
    print("WEB3---03: response payload",web3_res_payload)
    print("type of web3_response_payload: ",type(web3_res_payload))
    web3_res_body = json.loads(web3_res_payload['body'])
    print("type of web3_response_body: ",type(web3_res_body))
    
    
    # create bot response
    msg_body = ""
    msg_log = ""
    msg_hash = ""
    msg_address = ""
    msg_gas = ""
    msg_gas_used = ""
    msg_gas_fee = ""
    
    msg_body += "ガチャの結果により、%sまなびっとコインを獲得しました～。おめでとうございます～！\n" % (starcount)
    msg_log += "%s\n" % (web3_res_body['receipt']['etherscan'])
    msg_hash += "`%s`" % (web3_res_body["receipt"]["transactionHash"])
    msg_address += "`%s`" % (to_address)
    msg_gas += "`%s`" % (web3_res_body['receipt']['gasPriceString'])
    msg_gas_used += "`%s`" % (web3_res_body['receipt']['gasUsed'])
    msg_gas_fee += "`%s`" % (web3_res_body['receipt']['txFeeString'])
    
    attachments = []
    attachments.append(make_attachment(
        pretext='ガチャ結果をお伝えします〜！',
        color='#FFFF00',
        title='Manabit result',
        text='振込情報を羅列します〜！',
        fields=[
            {
                'title': 'MNBC ver holeskyをお届けします〜',
                'value': msg_body,
                # 'short': True
            },
            {
                'title': '<ログ>',
                'value': msg_log,
                # 'short': True
            },
            {
                'title': 'TRANSACTION HASH',
                'value': msg_hash,
                # 'short': True
            },
            {
                'title': 'RECEIVED ADDRESS',
                'value': msg_address,
                # 'short': True
            },
            {
                'title': 'GAS PRICE',
                'value': msg_gas,
                'short': True
            },
            {
                'title': 'GAS USED',
                'value': msg_gas_used,
                'short': True
            },
            {
                'title': 'TRANSACTION FEE',
                'value': msg_gas_fee,
                # 'short': True
            }
        ],
        footer='Powerd by web3 group'
    )
    )
    
    return attachments


def post_message(slack_client, channel, text, thread_ts):
    try:
        print(type(text))
        if type(text) is list:
            response = slack_client.chat_postMessage(
                channel=channel,
                attachments=text,
                as_user=True,
                thread_ts=thread_ts,
                reply_broadcast=False
            )
            print("slackResponse: ", response)
        else:
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


def make_attachment(
    pretext=None,
    color='#FFFFFF',
    author_name=None,
    author_link=None,
    author_icon=None,
    title=None,
    title_link=None,
    text=None,
    fields=None,
    footer=None,
    footer_icon=None,
    ts=None
):
    attachments = {
            'color': color,
            'pretext': pretext,
            'author_name': author_name,
            'author_link': author_link,
            'author_icon': author_icon,
            'title': title,
            'title_link': title_link,
            'text': text,
            'fields': fields,
            'footer': footer,
            'footer_icon': footer_icon,
            'ts': ts
    }
    return attachments
