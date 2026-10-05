PYTHON ?= python3
CC ?= gcc
CFLAGS ?= -g -O2 -Wall -Wextra

default: animate_server animate_client

libanimate:
	@if [ ! -d $@ ]; then \
		echo "ERROR: libanimate not found" > /dev/stderr; \
		false; \
	fi

libanimate_bridge.so: animate_bridge.c | libanimate
	$(CC) $(CFLAGS) -shared -fPIC $< -I libanimate/include -Llibanimate/lib -lanimate -o $@ -pthread

animate_server: animate_server.py libanimate_bridge.so
	cp animate_server.py $@
	chmod +x $@

animate_client: animate_client.py
	cp animate_client.py $@
	chmod +x $@

clean:
	rm -f animate_server animate_client libanimate_bridge.so FIFO_* *.dat *.mp4 *.log

