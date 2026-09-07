#!/bin/bash
set -euo pipefail

echo "Deleting Kind cluster 'aegis'..."
kind delete cluster --name aegis

echo "Cluster deleted."
