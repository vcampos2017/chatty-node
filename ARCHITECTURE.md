# Chatty Node Architecture

Chatty is designed as a **distributed civic AI network**, not a single device.

Each Chatty Node collects information from its local environment and contributes to a shared understanding of the surrounding world.

## Node Types

Examples of nodes in the network:

- Garden Node (soil moisture, plant health)
- Weather Node (temperature, humidity, pressure)
- Lightning Node (AS3935 detector)
- Environmental Node (CO₂, air quality)
- Civic Badge Node (wearable interface)

## System Layers

Sensors
↓
Local Edge Node (Raspberry Pi)
↓
Chatty Relay / AI Interface
↓
Human Interaction

## Design Philosophy

Chatty follows several guiding principles:

1. Process data locally whenever possible  
2. Respect privacy by default  
3. Share only necessary information  
4. Assist humans during emergencies  
5. Return to privacy mode automatically  
6. Cooperate with other nodes respectfully

## Concept

Rather than one centralized AI assistant, Chatty behaves like a **distributed civic intelligence**.

Each node contributes knowledge, but the **Chatty personality remains consistent across devices**.

In future implementations, Chatty could appear through many forms:

- a home assistant
- a weather station
- a wearable civic badge
- a watch or bracelet interface
- a public information kiosk

Chatty is therefore not a single device.

Chatty is a **network presence that moves with the user across nodes.**
