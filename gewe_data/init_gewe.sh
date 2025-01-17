#!/bin/bash

# API 服务地址
API_URL="http://gewe:2531/v2/api"
MAX_RETRIES=10  # 最大重试次数
RETRY_DELAY=5   # 重试间隔（秒）
QR_REFRESH_INTERVAL=60  # 每 1 分钟刷新二维码
AIRFLOW_VARIABLE_URL="http://airflow_web:80/api/v1/variables"

# 获取 Airflow 缓存的 token 和 appId
cached_token=$(curl --silent --location --request GET "$AIRFLOW_VARIABLE_URL/gewe_token" \
  --header "Authorization: Basic $(echo -n "${AIRFLOW_USERNAME}:${AIRFLOW_PASSWORD}" | base64)" | jq -r '.value')

cached_app_id=$(curl --silent --location --request GET "$AIRFLOW_VARIABLE_URL/gewe_app_id" \
  --header "Authorization: Basic $(echo -n "${AIRFLOW_USERNAME}:${AIRFLOW_PASSWORD}" | base64)" | jq -r '.value')

# Step 1: 获取 Token ID（如果没有缓存则获取新的）
if [ -z "$cached_token" ]; then
  echo "未找到缓存的 token，正在获取新的 token..."
  token_response=$(curl --silent --location --request POST "$API_URL/tools/getTokenId")
  token_id=$(echo "$token_response" | jq -r '.data')
  # 缓存新的 token
  curl --silent --location --request POST "$AIRFLOW_VARIABLE_URL" \
    --header "Content-Type: application/json" \
    --header "Authorization: Basic $(echo -n "${AIRFLOW_USERNAME}:${AIRFLOW_PASSWORD}" | base64)" \
    --data-raw '{
      "key": "gewe_token",
      "value": "'"$token_id"'"
    }'
else
  echo "找到缓存的 token: $cached_token"
  token_id=$cached_token
fi

# Step 2: 获取 appId（如果没有缓存则传空，自动创建设备）
if [ -z "$cached_app_id" ]; then
  echo "未找到缓存的 appId，正在获取新的 appId 和二维码..."
  login_response=$(curl --silent --location --request POST "$API_URL/login/getLoginQrCode" \
    --header "X-GEWE-TOKEN: $token_id" \
    --header 'Content-Type: application/json' \
    --data-raw '{"appId":""}')  # 初次登录传空，自动创建设备

  app_id=$(echo "$login_response" | jq -r '.data.appId')
  qr_img_base64=$(echo "$login_response" | jq -r '.data.qrImgBase64')
  uuid=$(echo "$login_response" | jq -r '.data.uuid')

  # 缓存新的 appId
  curl --silent --location --request POST "$AIRFLOW_VARIABLE_URL" \
    --header "Content-Type: application/json" \
    --header "Authorization: Basic $(echo -n "${AIRFLOW_USERNAME}:${AIRFLOW_PASSWORD}" | base64)" \
    --data-raw '{
      "key": "gewe_app_id",
      "value": "'"$app_id"'"
    }'
else
  echo "找到缓存的 appId: $cached_app_id"
  app_id=$cached_app_id

  # 使用已缓存的 appId 获取二维码
  login_response=$(curl --silent --location --request POST "$API_URL/login/getLoginQrCode" \
    --header "X-GEWE-TOKEN: $token_id" \
    --header 'Content-Type: application/json' \
    --data-raw '{"appId":"'"$app_id"'"}')
  
  qr_img_base64=$(echo "$login_response" | jq -r '.data.qrImgBase64')
  uuid=$(echo "$login_response" | jq -r '.data.uuid')
fi

# 输出二维码图片 (Base64 编码)
echo "请扫描以下二维码："
echo "$qr_img_base64" | base64 --decode > qr_code.png
echo "$qr_img_base64" | base64 --decode | cat
echo "二维码已保存为 qr_code.png。请扫描二维码进行登录。"

# Step 3: 检查登录状态，最多尝试 MAX_RETRIES 次
attempt=1
login_status=0

while [ "$attempt" -le "$MAX_RETRIES" ]; do
  # 每 1 分钟刷新一次二维码
  if [ "$attempt" -gt 1 ]; then
    echo "刷新二维码..."
    login_response=$(curl --silent --location --request POST "$API_URL/login/getLoginQrCode" \
      --header "X-GEWE-TOKEN: $token_id" \
      --header 'Content-Type: application/json' \
      --data-raw '{"appId":"'"$app_id"'"}')  # 使用上次登录的 appId

    qr_img_base64=$(echo "$login_response" | jq -r '.data.qrImgBase64')
    echo "请扫描新的二维码："
    echo "$qr_img_base64" | base64 --decode > qr_code.png
    echo "$qr_img_base64" | base64 --decode | cat
    echo "二维码已保存为 qr_code.png。请扫描二维码进行登录。"
  fi

  # 检查是否登录成功
  login_check_response=$(curl --silent --location --request POST "$API_URL/login/checkLogin" \
    --header "X-GEWE-TOKEN: $token_id" \
    --header 'Content-Type: application/json' \
    --data-raw '{"appId":"'"$app_id"'","uuid":"'"$uuid"'"}')

  login_status=$(echo "$login_check_response" | jq -r '.data.status')

  if [ "$login_status" == "1" ]; then
    echo "登录成功！"
    break
  else
    echo "登录未成功，正在第 $attempt 次重试..."
    attempt=$((attempt + 1))
    sleep "$RETRY_DELAY"  # 等待 5 秒后再重试
  fi
done

# 如果超过最大重试次数仍未成功，退出脚本
if [ "$login_status" != "1" ]; then
  echo "登录失败，超过最大重试次数，退出脚本。"
  exit 1
fi

# Step 4: 设置回调地址
callback_response=$(curl --silent --location --request POST "$API_URL/tools/setCallback" \
  --header "X-GEWE-TOKEN: $token_id" \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "token": "'"$token_id"'",
    "callbackUrl": "http://192.168.29.1:8080/v2/api/callback/collect"
  }')

echo "设置回调地址成功，开始将数据缓存到 Airflow 变量..."

# Step 5: 将数据缓存到 Airflow 变量
curl --location --request POST "$AIRFLOW_VARIABLE_URL" \
  --header "Content-Type: application/json" \
  --header "Authorization: Basic $(echo -n "${AIRFLOW_USERNAME}:${AIRFLOW_PASSWORD}" | base64)" \
  --data-raw '{
    "key": "gewe_token",
    "value": "'"$token_id"'"
  }'

curl --location --request POST "$AIRFLOW_VARIABLE_URL" \
  --header "Content-Type: application/json" \
  --header "Authorization: Basic $(echo -n "${AIRFLOW_USERNAME}:${AIRFLOW_PASSWORD}" | base64)" \
  --data-raw '{
    "key": "gewe_app_id",
    "value": "'"$app_id"'"
  }'

echo "初始化并缓存变量完成。"
