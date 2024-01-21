#!/bin/bash

pyFlag=0

python resources/App.py
if [ $? -ne 0 ]; then
    echo "An error occurred while running App.py"
    read -p "Press Enter to continue..."
    pyFlag=1
fi

if [ "$pyFlag" -eq 1 ]; then
    python resources/App.py
    if [ $? -ne 0 ]; then
        echo "An error occurred while running App.py"
        read -p "Press Enter to continue..."
    fi
fi