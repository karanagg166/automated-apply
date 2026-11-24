// Browser port double for tests that already provide a one-message host.
export function fixtureNativePort(runtime, host) {
  const messages = new Set();
  const disconnects = new Set();
  const event = (listeners) => ({
    addListener: (listener) => listeners.add(listener),
    removeListener: (listener) => listeners.delete(listener),
  });
  return {
    onMessage: event(messages),
    onDisconnect: event(disconnects),
    postMessage(request) {
      void runtime.sendNativeMessage(host, request).then(
        (response) => {
          for (const listener of messages) listener(response);
        },
        () => {
          for (const listener of disconnects) listener();
        },
      );
    },
    disconnect() {
      messages.clear();
      disconnects.clear();
    },
  };
}
