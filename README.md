# make .env or set ENVIRONMENT
```
ENV_SECRET_NAME=
ENV_REGION_NAME=ap-northeast-1
ENV_SYSTEM_PROMPT_BASE=system_prompt/hiroyuki.txt
ENV_SYSTEM_PROMPT_GACHA=system_prompt/gacha.txt
ENV_GPT_MODEL=gpt-3.5-turbo-0613
ENV_LAMBDA_INVOKE=
```


# set key-value on AWS secret manager
```
SLACK_OAUTH_TOKEN
OPENAI_ORGANIZATION
OPENAI_API_KEY
EOA_SST_FUND
```


# ----------ENVIRONMENT for ver manabot03----------

## make .env or set ENVIRONMENT
```
ENV_SECRET_NAME=
ENV_REGION_NAME=ap-northeast-1
ENV_SYSTEM_PROMPT_BASE=system_prompt/monoshiru.txt
ENV_SYSTEM_PROMPT_GACHA=system_prompt/gacha.txt
ENV_GPT_MODEL=gpt-4-1106-preview
ENV_LAMBDA_INVOKE=
```

## set key-value on AWS secret manager
Pls allocate these info in SecretManager
```
SLACK_OAUTH_TOKEN=
OPENAI_ORGANIZATION=
OPENAI_API_KEY=
EOA_SST_FUND=
SLACKBOT_OAUTH_TOKEN=
```

## make api-gateway
Used with Slack Bot.  
Connection with Slack is done through API-Gateway.  
Therefore, it is necessary to create API-Gateway as a trigger.
