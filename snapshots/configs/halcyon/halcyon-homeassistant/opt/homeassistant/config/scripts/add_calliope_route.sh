#!/bin/bash

# Add routes for Calliope network
# Script: add_calliope_route.sh

# Add the routes (suppress error output to avoid issues with existing routes)
ip route add 10.1.1.0/24 via 10.2.1.100 2>/dev/null
ip route add 100.64.0.0/10 via 10.2.1.100 2>/dev/null

# Exit successfully regardless of whether routes were added or already existed
exit 0