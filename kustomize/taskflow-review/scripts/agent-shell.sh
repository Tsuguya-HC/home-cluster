#!/bin/sh
# 1 プロセスのヒープを AGENT_DATA_LIMIT で抑える。
# --as にしない: Node（V8）が大きな仮想領域を予約し、vitest が起動できない。
exec prlimit --data="${AGENT_DATA_LIMIT:?}" -- /bin/bash -c "$1"
