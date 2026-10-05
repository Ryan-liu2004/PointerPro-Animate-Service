CFLAGS = -fno-sanitize=all -Wvla -Werror -fsanitize=address -g -Wall -Wextra
FLAGS = -Wall -Wextra

default: animate_server animate_client

libanimate:
	@if [ ! -d $@ ]; then \
		echo "ERROR: libanimate not found" > /dev/stderr; \
		echo "Download and unzip libanimate.zip from P2 resources" > /dev/stderr; \
		false; \
	fi

server: animate_server.c tool.c vector.c thread_pool.c queue.c timer.c rpc.c rpc_tool.c rpc_cleanup.c | libanimate
	gcc $(CFLAGS) $^ -I libanimate/include -Llibanimate/lib -lanimate -o $@ -pthread

client: animate_client.c tool.c vector.c
	gcc $(CFLAGS) $^ -o $@

animate_server: animate_server.c tool.c vector.c thread_pool.c queue.c timer.c rpc.c rpc_tool.c rpc_cleanup.c | libanimate
	gcc $(FLAGS) $^ -I libanimate/include -Llibanimate/lib -lanimate -o $@ -pthread

animate_client: animate_client.c tool.c vector.c
	gcc $(FLAGS) $^ -o $@

clean:
	rm -f animate_server animate_client FIFO_* server client
