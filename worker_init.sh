#!/bin/bash
set -e
set -x

sudo apt install -y proot

/sio2/oioioi/wait-for-it.sh -t 60 "db:5432"
/sio2/oioioi/wait-for-it.sh -t 0  "web:8000"

mkdir -pv /sio2/logs/{supervisor,runserver,database}

echo "LOG: Downloading sandboxes"
mkdir -pv /sio2/sandboxes
./manage.py download_sandboxes -y -d /sio2/sandboxes

echo "LOG: Launching worker at `hostname`"
export SIOWORKERSD_HOST="dev-worker"
export FILETRACKER_URL="http://web:9999"
twistd --nodaemon --pidfile=/home/oioioi/worker.pid \
        -l /sio2/logs/worker`hostname`.log worker \
        -n worker`hostname` -c 2 web \
        > /sio2/logs/twistd_worker.out \
        2> /sio2/logs/twistd_worker.err
