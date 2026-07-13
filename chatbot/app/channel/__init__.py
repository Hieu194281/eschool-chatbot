"""Messenger channel adapter: webhook → verify → ACK → dedupe → debounce →
single-flight → graph → send. Adapter interface lets Zalo drop in later."""
