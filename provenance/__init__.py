"""Provenance: an AML triage agent that cannot emit an uncited assertion."""
import os

# gRPC (Firestore's transport) ships its own c-ares DNS resolver, which fails on some macOS
# networks ("DNS query cancelled") where the system resolver works. Use the OS resolver.
# Set here because this package is imported before any Google client in every entry point.
os.environ.setdefault("GRPC_DNS_RESOLVER", "native")
