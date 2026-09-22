#!/bin/sh
set -e

until mongosh --host mongodb --quiet --eval "db.adminCommand('ping')" >/dev/null 2>&1; do
  echo "Waiting for mongodb..."
  sleep 2
done

STATUS=$(mongosh --host mongodb --quiet --eval "rs.status().ok" 2>/dev/null || echo "0")
if [ "$STATUS" != "1" ]; then
  echo "Initiating replica set..."
  mongosh --host mongodb --eval "rs.initiate({_id: 'rs0', members: [{_id: 0, host: 'mongodb:27017'}]})"
else
  echo "Replica set already initiated."
fi
