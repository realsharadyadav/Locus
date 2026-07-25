#!/usr/bin/env python3
"""Run a 100-step web_research conversation and leave it for the user to inspect."""
import requests, json, time, random

BASE = "http://127.0.0.1:8000"

TOPICS = [
    "What is the current state of quantum computing in 2026?",
    "How do large language models work under the hood?",
    "What are the latest breakthroughs in fusion energy?",
    "Compare Rust and Go for systems programming",
    "What is Retrieval Augmented Generation?",
    "How does Kubernetes handle auto-scaling?",
    "What are the best practices for REST API design?",
    "Explain the CAP theorem with real-world examples",
    "What is WebAssembly and where is it used today?",
    "How do neural networks learn through backpropagation?",
    "What are the trade-offs between SQL and NoSQL databases?",
    "What is the current state of autonomous vehicles?",
    "How does CRISPR gene editing work?",
    "Explain the concept of zero-knowledge proofs",
    "What are microservices and when should you use them?",
    "How does TLS 1.3 improve upon TLS 1.2?",
    "What is edge computing and why does it matter?",
    "Explain the Raft consensus algorithm",
    "What are the latest developments in solid-state batteries?",
    "How does Docker differ from virtual machines?",
    "What is the significance of Moore's Law ending?",
    "Explain event-driven architecture with examples",
    "What are the top cybersecurity threats in 2026?",
    "How does GraphQL compare to REST?",
    "What is the current state of brain-computer interfaces?",
    "Explain the Observer pattern in software design",
    "What are progressive web apps and their advantages?",
    "How does continuous integration and deployment work?",
    "What is the Internet of Things security challenge?",
    "Explain distributed caching strategies",
    "What are the implications of RISC-V architecture?",
    "How does a compiler work from source to machine code?",
    "What is serverless computing and its limitations?",
    "Explain the difference between threads and processes",
    "What are digital twins and their industrial applications?",
    "How does HTTPS certificate transparency work?",
    "What is the current state of 6G research?",
    "Explain the SOLID principles in object-oriented design",
    "What are the challenges of multi-cloud deployments?",
    "How does the HTTP/3 protocol improve performance?",
    "What is formal verification in software engineering?",
    "Explain eventual consistency in distributed systems",
    "What are the ethical concerns of facial recognition AI?",
    "How does a load balancer algorithm work?",
    "What is the current state of quantum error correction?",
    "Explain the actor model in concurrent programming",
    "What are the benefits of infrastructure as code?",
    "How does DNS resolution actually work?",
    "What is the significance of the NIST post-quantum standards?",
    "Explain the differences between REST and gRPC",
    "What are WebSockets and when to use them over HTTP?",
    "How does garbage collection work in the JVM?",
    "What is chaos engineering and why practice it?",
    "Explain the CAP theorem revisited in modern systems",
    "What are the latest developments in neuromorphic computing?",
    "How does a Kubernetes service mesh work?",
    "What is the role of observability in modern software?",
    "Explain functional reactive programming",
    "What are the trade-offs in database sharding?",
    "How does encryption at rest differ from in transit?",
    "What is the current state of natural language processing?",
    "Explain the concept of technical debt",
    "What are the advantages of Rust memory safety?",
    "How does a message queue like Kafka work?",
    "What is platform engineering and how does it relate to DevOps?",
    "Explain the Byzantine generals problem",
    "What are the latest advances in protein folding prediction?",
    "How does container orchestration differ from container management?",
    "What is the role of API gateways in microservices?",
    "Explain eventual consistency vs strong consistency",
    "What are the challenges of real-time data processing?",
    "How does Git handle merge conflicts internally?",
    "What is the significance of ARM processors in cloud computing?",
    "Explain the concept of technical architecture layers",
    "What are the current trends in AI agent frameworks?",
    "How does a distributed transaction work across microservices?",
    "What is the SOLID architecture principle revisited?",
    "Explain the differences between monorepo and polyrepo",
    "What are the implications of memory-safe programming languages?",
    "How does rate limiting work in distributed systems?",
    "What is the current state of homomorphic encryption?",
    "Explain the circuit breaker pattern in distributed systems",
    "What are the best practices for database indexing?",
    "How does time-series data differ from regular data?",
    "What is the concept of shift-left testing?",
    "Explain the Strangler Fig pattern in software migration",
    "What are the challenges of running AI models on edge devices?",
    "How does connection pooling work in database systems?",
    "What is the future of WebAssembly beyond browsers?",
    "Explain the difference between concurrency and parallelism",
    "What are the trade-offs between horizontal and vertical scaling?",
    "How does a reverse proxy improve security and performance?",
    "What is the current state of decentralized identity?",
    "Explain feature flags and their role in progressive delivery",
    "What are the challenges of testing distributed systems?",
    "How does consistent hashing work?",
    "What is the concept of chaos monkey and resilience engineering?",
    "Explain the differences between optimistic and pessimistic locking",
    "What are the latest developments in satellite internet?",
    "How does a service discovery mechanism work?",
    "What is the role of policy as code in cloud governance?",
    "Explain the concept of data mesh architecture",
    "How do AI agents differ from simple chatbots?",
]

followups = [
    "Can you go deeper on that topic?",
    "What are the practical implications?",
    "How does that compare to alternatives?",
    "What are the main challenges with this approach?",
    "Give me real-world examples of this",
    "What do the latest sources say about this in 2026?",
    "How is this technology evolving right now?",
    "What are the trade-offs to consider?",
    "How do industry experts debate this?",
    "What resources should I explore next on this?",
]

chat_id = None
total_time = 0
total_sources = 0
consecutive_errors = 0
success_count = 0

for step in range(1, 101):
    if step <= len(TOPICS):
        question = TOPICS[step - 1]
    else:
        question = random.choice(followups)

    print(f"\n--- Step {step}/100 ---", flush=True)
    print(f"Q: {question[:80]}...", flush=True)

    start = time.time()
    try:
        resp = requests.post(
            f"{BASE}/api/chat/stream",
            json={
                "question": question,
                "conversation_id": chat_id,
                "reasoning_mode": "web_research",
                "file_ids": [],
                "web_source_limit": 8,
            },
            stream=True,
            timeout=180,
        )

        answer_text = ""
        sources = []
        error_found = False

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = evt.get("type")
            if etype == "stage":
                pass  # progress events, skip
            elif etype == "result":
                data = evt.get("data", {})
                answer_text = data.get("answer", "")
                sources = data.get("sources", [])
                if not chat_id:
                    chat_id = data.get("conversation_id")
            elif etype == "error":
                print(f"  ERROR: {evt.get('detail', 'unknown')}", flush=True)
                error_found = True
                consecutive_errors += 1
                break

        elapsed = time.time() - start
        total_time += elapsed
        src_count = len(sources)
        total_sources += src_count
        answer_preview = answer_text[:150].replace("\n", " ")
        print(f"  A: {answer_preview}...", flush=True)
        print(f"  Sources: {src_count} | Time: {elapsed:.1f}s | Chat: {chat_id}", flush=True)

        if not error_found:
            consecutive_errors = 0
            success_count += 1

        if consecutive_errors >= 5:
            print("\n!!! 5 consecutive errors - stopping !!!", flush=True)
            break

    except requests.exceptions.Timeout:
        print(f"  TIMEOUT after 180s", flush=True)
        consecutive_errors += 1
    except Exception as e:
        print(f"  EXCEPTION: {e}", flush=True)
        consecutive_errors += 1

    time.sleep(0.3)

print(f"\n{'='*60}", flush=True)
print(f"DONE! Chat ID: {chat_id}", flush=True)
print(f"Successful steps: {success_count}/100", flush=True)
print(f"Total time: {total_time:.0f}s | Avg: {total_time/max(success_count,1):.1f}s/step", flush=True)
print(f"Total sources collected: {total_sources}", flush=True)
print(f"View at: http://127.0.0.1:5173/", flush=True)
