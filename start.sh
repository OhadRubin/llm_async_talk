lsof -ti:8894 | xargs kill -9
open /Applications/Docker.app
sleep 10
docker-compose up -d --build
sleep 5
trap 'docker-compose down; exit' INT
python cli_chatroom_client.py