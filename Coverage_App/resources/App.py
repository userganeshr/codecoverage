import importlib
import subprocess

try:
    importlib.import_module('Pillow')
    importlib.import_module('tkinter')
    importlib.import_module('Jinja2')
    print("Pillow and Tkinter packages are installed.")
except ImportError:
    print("Pillow and Tkinter packages are not installed.")
    print("Installing Pillow and Tkinter packages...")
    subprocess.check_call(["python", "-m", "pip", "install", "Pillow", "tk", "Jinja2"])

import tkinter as tk
from tkinter import filedialog
from tkinter import ttk
from PIL import Image, ImageTk
import threading
import os
from jinja2 import Template
import re


# Define the Bash script content
bash_script = r'''
#!/bin/bash

# Get the script's directory
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

output_file="${script_dir}/$(basename "$1" .txt)_nonulls.txt"

tr -cd '\11\12\15\40-\176' < "$1" > "$output_file"

# Convert from DOS text file
dos2unix "$output_file"

# Create separate .gcda.xxd files from the serial log
# The files can be created at the full pathname specified in the log
# or can be created in the current directory, see serial_split.awk.
# Current directory is more convenient for us here.
cat "$output_file" | awk -f "${script_dir}/serial_split.awk"

# Initialize an empty array to store .info files
info_files=()

path=$(grep -oE '/home/[^[:space:]]+\.gcda' "$output_file" | awk '!seen[$0]++')

name=${path#*Application/}
name=${name%CMakeFiles*}
application_name=${name%%/*}

# List all .gcda.xxd files in the current directory
for file_name in *.gcda.xxd; do
	# Extract the base file name without extension
	base_name="${file_name%.*}"

	cov_name="${file_name%.cpp*}"

	# Filter out base_name with .gcda extension
	# Find the corresponding path in ${1%.*}_nonulls_no_duplicates.txt
	paths=$(grep -oE '/home/[^[:space:]]+\.gcda' "$output_file" | grep "$base_name" | awk '!seen[$0]++')

	# Loop over each path and move the file
    while IFS= read -r dir_path; do
        if [ -n "$dir_path" ]; then
            # Extract the actual destination directory
            actual_dir_path=$(dirname "$dir_path")

            mv "$file_name" "$actual_dir_path"

            echo "Moved: $file_name to $actual_dir_path"

			# Convert the .gcda.xxd files to .gcda and remove the .xxd files
			for i in `find "$actual_dir_path" -name '*.gcda.xxd'`;do
				cat "$i" | xxd -r > "${i/\.xxd/}"
				rm "$i"
			done
			lcov --gcov-tool gcov --capture --rc lcov_branch_coverage=1 --directory "$actual_dir_path" --output-file "$actual_dir_path"/${cov_name%.*}.info 
			
			info_files+=("$actual_dir_path/${cov_name%.*}.info")
        else
            echo "No matching path found for $file_name"
        fi
    done <<< "$paths"
done

lcov --zerocounters --output-file "$script_dir/${application_name%.*}filter_output.info"

# Combine all .info files
for file in "${info_files[@]}"; do
  echo "Processing file $file"
  lcov_input_files="$lcov_input_files -a \"$file\""
done

eval lcov $lcov_input_files --output-file "$script_dir/${application_name%.*}filter_output.info" --rc lcov_branch_coverage=1

lcov --extract "$script_dir/${application_name%.*}filter_output.info" '*/Application/*' --output-file "$script_dir/${application_name%.*}combined_output.info" --rc lcov_branch_coverage=1

input_file="$script_dir/${application_name%.*}combined_output.info"
output_directory="$script_dir/Reports/${application_name%.*}/CoverageReport"

# Generate the HTML coverage report from the combined .info file
genhtml "$input_file" --output-directory "$output_directory" --rc genhtml_branch_coverage=1

# Remove the combined_lcov.info file after generating HTML files
rm $script_dir/${application_name%.*}combined_output.info
rm $script_dir/${application_name%.*}filter_output.info
rm "$output_file"
'''

awk_file = r'''
#!/usr/bin/awk -f

BEGIN {
    init = 0;
    tstr = "";
    output_dir = ".";  # Set the default output directory to the current directory
}

/Emit/ {
    print;
    init = 1;
    tstr = "";
    next;
}

/__gcov_init/ {
    init = 0;
    tstr = "";
    next;
}

!/gcda/ {
    if (!init || !NF) {
        next;
    }
    tstr = tstr "" $0 "\n";
    next;
}

/gcda/ {
    if (!init) {
        next;
    }

    # Extract the file name using awk
    cmd = "basename " $0;
    cmd | getline fname;
    close(cmd);

    # Construct the full path for the output file
    full_path = output_dir "/" fname ".xxd";

    # Print the content to the output file
    print tstr > full_path;

    # On to the next file
    init = 0;
    tstr = "";
    next;
}

'''



class GTestReportGenerator:
    def __init__(self):
        self.submodulepath='States'
    def parse_gtest_output(self,gtest_output):

        total_test_info_line = next((line for line in gtest_output if "tests from" in line), "")

        total_test_match = re.search(r'Running (\d+) tests? from (\d+) test suites?', total_test_info_line.strip())

        total_test_cases = int(total_test_match.group(1)) if total_test_match else 0
        total_test_suites = int(total_test_match.group(2)) if total_test_match else 0
        total_failed_testcase = 0
        total_passed_testcase = 0

        test_suite_data = []
        current_test_suite = None
        test_cases = []
        failed_test_cases = 0
        passed_test_cases = 0
        

        for line in gtest_output:
            if "Running main()" in line:
                # Extract the module name
                module_name_match = re.search(r'/Application/(\w+)/UnitTest/', line)
                self.module_name = module_name_match.group(1) if module_name_match else None
            if "[----------]" in line and "tests from" in line or "[----------]" in line and "test from" in line:
                if current_test_suite is not None:
                    test_suite_data.append((current_test_suite, len(test_cases), failed_test_cases, passed_test_cases, test_cases))
                    test_cases = []
                    total_failed_testcase+=failed_test_cases
                    total_passed_testcase+=passed_test_cases
                    failed_test_cases = 0
                    passed_test_cases = 0
                current_test_suite_match = re.search(r'from (\S+)', line)
                current_test_suite = current_test_suite_match.group(1) if current_test_suite_match else None
            elif "[ RUN      ]" in line:
                test_case_name = line.split()[-1].split('.')[-1]  # Extract only the test case name
                test_cases.append({"name": test_case_name, "status": None})
            elif "[       OK ]" in line:
                test_cases[-1]["status"] = "Pass"
                passed_test_cases += 1
            elif "[  FAILED  ]" in line:
                if test_cases:  # Check if there are any test cases recorded
                    test_cases[-1]["status"] = "Fail"
                    failed_test_cases += 1

        if current_test_suite is not None:
            test_suite_data.append((current_test_suite, len(test_cases), failed_test_cases, passed_test_cases, test_cases))

        # Remove lines with "total): 0 test cases"
        test_suite_data = [(name, count, failed_count, passed_count, cases) for name, count, failed_count, passed_count, cases in test_suite_data if count > 0]

        return test_suite_data, total_test_suites, total_test_cases, total_passed_testcase, total_failed_testcase 


    def generate_main_html_report(self,test_suite_data, total_test_suites, total_test_cases, total_passed_testcase, total_failed_testcase):
        template_str = '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Test Report</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    background-color: #f4f4f4;
                }

                h1 {
                    color: #007BFF;
                    text-align: center;
                }

                h2 {
                    color: #333;
                    text-align: center;
                }

                table {
                    border-collapse: collapse;
                    width: 80%;
                    margin-top: 20px;
                    margin-left: auto;
                    margin-right: auto;
                }

                th, td {
                    border: 1px solid #ddd;
                    padding: 12px;
                    text-align: left;
                }

                th {
                    background-color: #007BFF;
                    color: white;
                }

                a {
                    text-decoration: none;
                    color: #007BFF;
                }

                .total-info {
                    font-weight: bold;
                    font-size: 18px;
                    margin-bottom: 20px;
                    text-align: center;
                }
                .tab { 
                    display: inline-block; 
                    margin-left: 150px; 
                } 
            </style>
        </head>
        <body>
            <h1>Test Report</h1>
            <div class="total-info">
                <p>Total Test Suites: {{ total_test_suites }}
                <span class="tab"></span>
                Total Test Cases: {{ total_test_cases }}</p>
                Total Pass: {{ total_passed_testcase }}</p>
                Total Fail: {{ total_failed_testcase }}</p>
            </div>

            <table>
                <tr>
                    <th>Test Suite</th>
                    <th>Number of Test Cases</th>
                    <th>Number of Passed Test Cases</th>
                    <th>Number of Failed Test Cases</th>
                </tr>
                {% for test_suite, test_case_count, failed_count, passed_count, _ in test_suite_data %}
                    <tr>
                        <td><a href="{{ test_suite }}.html" style="color: {% if failed_count > 0 %}red{% else %}#007BFF{% endif %}">{{ test_suite }}</a></td>
                        <td>{{ test_case_count }}</td>
                        <td>{{ passed_count }}</td>
                        <td>{{ failed_count }}</td>
                    </tr>
                {% endfor %}
            </table>
        </body>
        </html>
        '''
        # Get the current working directory
        script_dir = os.path.dirname(os.path.abspath(__file__))

        full_path = os.path.abspath(os.path.join(script_dir, 'Reports', self.module_name ,'TestReport'))
        if not os.path.exists(full_path):
            os.makedirs(full_path)
        template = Template(template_str)
        with open(os.path.join(full_path, 'main_test_report.html'), 'w') as f:
            f.write(template.render(test_suite_data=test_suite_data, total_test_suites=total_test_suites, total_test_cases=total_test_cases, total_passed_testcase=total_passed_testcase, total_failed_testcase=total_failed_testcase))


    def generate_suite_html_report(self,test_suite, test_case_count, failed_count, passed_count, test_cases):
        template_str = '''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{{ test_suite }} Test Suite</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    background-color: #f4f4f4;
                }

                h2 {
                    color: #333;
                    text-align: center;
                }

                h3 {
                    color: #333;
                    text-align: center;
                }

                table {
                    border-collapse: collapse;
                    width: 80%;
                    margin-top: 20px;
                    margin-left: auto;
                    margin-right: auto;
                }

                th, td {
                    border: 1px solid #ddd;
                    padding: 12px;
                    text-align: left;
                }

                th {
                    background-color: #007BFF;
                    color: white;
                }

                td.test-case-name {
                    color: #007BFF;
                }

                span.pass {
                    color: #28a745;
                    font-weight: bold;
                }

                span.fail {
                    color: #dc3545;
                    font-weight: bold;
                }
            </style>
        </head>
        <body>
            <h2>Total Test Cases in {{ test_suite }}: {{ test_case_count }}</h2>
            <h3>Number of Passed Test Cases: {{ passed_count }}</h3>
            <h3>Number of Failed Test Cases: {{ failed_count }}</h3>

            <table>
                <tr>
                    <th>Test Case Name</th>
                    <th>Status</th>
                </tr>
                {% for test_case in test_cases %}
                    <tr>
                        <td class="test-case-name">{{ test_case["name"] }}</td>
                        <td>
                            {% if test_case["status"] == "Pass" %}
                                <span class="pass">Pass</span>
                            {% else %}
                                <span class="fail">Fail</span>
                            {% endif %}
                        </td>
                    </tr>
                {% endfor %}
            </table>
        </body>
        </html>
        '''
        
        # Get the current working directory
        script_dir = os.path.dirname(os.path.abspath(__file__))

        full_path = os.path.abspath(os.path.join(script_dir, 'Reports', self.module_name, 'TestReport'))

        template = Template(template_str)
        with open(os.path.join(full_path, f'{test_suite}.html'), 'w') as f:
            f.write(template.render(test_suite=test_suite, test_case_count=test_case_count, failed_count=failed_count, passed_count=passed_count, test_cases=test_cases))

    def handle_testreport(self, selected_file_path):
            with open(selected_file_path , 'r') as file:
                gtest_output = file.readlines()

            test_suite_data, total_test_suites, total_test_cases, total_passed_testcase, total_failed_testcase  = self.parse_gtest_output(gtest_output)
            self.generate_main_html_report(test_suite_data, total_test_suites, total_test_cases, total_passed_testcase, total_failed_testcase)
            for test_suite, test_case_count, failed_count, passed_count, test_cases in test_suite_data:
                self.generate_suite_html_report(test_suite, test_case_count, failed_count, passed_count, test_cases)

class TextFileSelectorApp:
    def __init__(self, master, gtest_report_generator):
        self.master = master
        self.master.title("Report Generator")
        self.script_running = False  # Flag to track whether the script is running
        self.generate_button = None  # Initialize to None
        self.coverage_var = tk.IntVar()
        self.test_var = tk.IntVar()

        # Initialize frames
        self.file_selector_frame = tk.Frame(self.master)
        self.second_screen_frame = None  # Initialize to None
        self.selected_folder = ''  # Initialize selected_folder

        self.gtest_report_generator = gtest_report_generator

        self.bashscript_path=''
        self.awk_path=''

        # Set up the file selector frame
        self.setup_file_selector_frame()

    def setup_file_selector_frame(self):

        # Get the absolute path to the script
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Specify the relative path to the image file
        image_path = os.path.join(script_dir, 'open_file_image.png')
        # Load an image for the Open File button
        open_image = Image.open(image_path)  # Replace "open_file_image.png" with your image file
        open_image = open_image.resize((100, 100))
        open_photo = ImageTk.PhotoImage(open_image)

        # Create and configure the Open File button with the image and text
        open_button = tk.Button(self.file_selector_frame, text="Open File", image=open_photo, compound=tk.TOP, command=self.open_file_dialog, bd=0, relief=tk.FLAT)
        open_button.image = open_photo  # Keep a reference to the image
        open_button.pack(pady=20)

        # Center the file selector frame within the main window
        self.file_selector_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def open_file_dialog(self):
        file_path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if file_path:
            print(f"Selected file: {file_path}")
            self.selected_file_path = file_path  # Store the selected file path for later use
            self.show_second_screen()

    def show_second_screen(self):
        # Hide the file selector frame
        self.file_selector_frame.place_forget()

        # Destroy the existing second screen frame if it exists
        if self.second_screen_frame:
            self.second_screen_frame.destroy()

        with open(self.selected_file_path , 'r') as file:
            gtest_output = file.readlines()

        for line in gtest_output:
            if "Running main()" in line:
                # Extract the module name
                module_name_match = re.search(r'/Application/(\w+)/UnitTest/', line)
                self.module_name = module_name_match.group(1) if module_name_match else None
                break

        # Set up the second screen frame
        self.setup_second_screen_frame(selected_folder=self.selected_folder)

        # Show the second screen frame
        self.second_screen_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)


    def setup_second_screen_frame(self, selected_folder):
        # Create a new instance of the second screen frame
        self.second_screen_frame = tk.Frame(self.master)

        # Create and configure Coverage Report checkbox
        coverage_checkbox = tk.Checkbutton(self.second_screen_frame, text="Coverage Report", variable=self.coverage_var, font=("Arial", 15), anchor="w", height=3, width=20)
        coverage_checkbox.pack()

        # Create and configure Test Report checkbox
        test_checkbox = tk.Checkbutton(self.second_screen_frame, text="Test Report", variable=self.test_var, font=("Arial", 15), anchor="w", height=3, width=20)
        test_checkbox.pack()

        # Create progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.second_screen_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(pady=10)

        # Create a frame for Back and Generate buttons
        button_frame = tk.Frame(self.second_screen_frame)

        # Create and configure the Generate button
        self.generate_button = tk.Button(button_frame, text="Generate", command=self.generate_reports, bd=0, relief=tk.FLAT, bg="#7f8285", fg="white", font=("Arial", 10))
        self.generate_button.pack(side="left", padx=10)

        # Create and configure the Back button
        self.back_button = tk.Button(button_frame, text="Back", command=self.show_file_selector_frame, bd=0, relief=tk.FLAT, bg="#7f8285", fg="white", font=("Arial", 10))
        self.back_button.pack(side="left", padx=10)

        # Pack the button frame
        button_frame.pack(pady=20)

        # Hide the progress bar initially
        self.progress_bar.pack_forget()

        # Create a menu bar
        menu_bar = tk.Menu(self.second_screen_frame)

        # Create a "File" menu
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Coverage Report", command=lambda: self.open_report(selected_folder, "coverage"))
        file_menu.add_command(label="Test Report", command=lambda: self.open_report(selected_folder, "test"))

        # Add the "File" menu to the menu bar
        menu_bar.add_cascade(label="Open", menu=file_menu)

        # Set the menu bar for the second screen frame
        self.master.config(menu=menu_bar)


    def perform_operation(self, selected_folder):
        # Implement your logic to perform an operation with the selected folder
        print(f"Performing operation with folder: {selected_folder}")

                # Create a new window to display options
        options_window = tk.Toplevel(self.master)
        options_window.title("Select Report Type")

        # Create buttons for Test Report and Coverage Report
        test_button = tk.Button(options_window, text="Test Report", command=lambda: self.open_report(selected_folder, "test"))
        coverage_button = tk.Button(options_window, text="Coverage Report", command=lambda: self.open_report(selected_folder, "coverage"))

        # Pack the buttons
        test_button.pack(pady=10)
        coverage_button.pack(pady=10)


    def open_report(self, selected_folder, report_type):
        # Implement logic to open the selected report type in the default web browser
        print(f"Opening {report_type} report for folder: {selected_folder}")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the HTML file path based on the selected report type
        if report_type == "test":
            selected_folder = "TestReport"
            html_file_path = os.path.join(script_dir, "Reports", self.module_name, selected_folder, "main_test_report.html")
        elif report_type == "coverage":
            selected_folder = "CoverageReport"
            html_file_path = os.path.join(script_dir, "Reports", self.module_name, selected_folder, "index.html")
        else:
            return  # Invalid report type

        # Check if the HTML file exists before opening
        if os.path.exists(html_file_path):
            try:
                # Use subprocess to open the HTML file in the default web browser
                subprocess.run(["explorer.exe", html_file_path.replace("/", "\\")], check=True)
            except subprocess.CalledProcessError as e:
                print(f"Error opening web browser: {e}")
        else:
            print(f"{report_type} report not found in {selected_folder}")


    def generate_reports(self):
        # Check the selected checkboxes and trigger the corresponding actions
        if self.coverage_var.get() == 1 or self.test_var.get() == 1:
            self.show_progress_bar()
            if self.coverage_var.get() == 1:
                self.run_coverage_report()
            if self.test_var.get() == 1:
                self.run_test_report()

    def run_test_report(self):
        # Implement the test report generation logic here
        if hasattr(self, 'selected_file_path') and not self.script_running:
            print("Generating Test Report...")
            # Add your logic to run the Python script for the test report here
            self.gtest_report_generator.handle_testreport(self.selected_file_path)

            # Reset the flag to indicate that the script has completed
            self.script_running = False

            # Update the progress bar to 100%
            self.progress_var.set(100)

            # Script has completed successfully
            print("Script completed!")

            # Add code to display the work completed screen
            self.testreport_complete_screen()

    def run_coverage_report(self):
        if hasattr(self, 'selected_file_path') and not self.script_running:
            # Set the flag to indicate that the script is running
            self.script_running = True

            # Disable the Get Coverage Report button
            self.generate_button['state'] = tk.DISABLED

            # Disable the Back button
            self.back_button['state'] = tk.DISABLED

            # Get the absolute path to the script
            script_dir = os.path.dirname(os.path.abspath(__file__))

            awkfile_path = script_dir+'/serial_split.awk'
            with open(awkfile_path, 'w') as script_file:
                script_file.write(awk_file)

            # Run your bash script with the selected text file path in a separate thread
            bash_script_path = script_dir+'/gcov_convert.sh'
            with open(bash_script_path, 'w') as script_file:
                script_file.write(bash_script)

            file_path = self.selected_file_path
            self.bashscript_path=bash_script_path
            self.awk_path=awkfile_path
            try:
                # Define a function to run in a separate thread
                def run_script():
                    process = subprocess.Popen(['bash', bash_script_path, file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    process_output = process.communicate()[0].decode('utf-8')

                    # Notify the main thread that the subprocess has completed
                    self.master.event_generate("<<ProcessCompleted>>", when="tail")
                    self.master.process_output = process_output

                    # Reset the flag to indicate that the script has completed
                    self.script_running = False

                # Start a thread to run the script
                self.master.thread = threading.Thread(target=run_script)
                self.master.thread.start()

                # Bind the ProcessCompleted event to a method that will be called when the subprocess completes
                self.master.bind("<<ProcessCompleted>>", self.process_completed)

                # Start updating the progress bar while the subprocess is running
                self.update_progress()

            except subprocess.CalledProcessError as e:
                print(f"Error running Bash script: {e}")


    def update_progress(self):
        # Update the progress bar while the subprocess is running
        if hasattr(self, 'selected_file_path') and hasattr(self.master, 'thread') and self.master.thread.is_alive():
            # Simulate progress by incrementing the progress bar value
            current_value = self.progress_var.get()
            new_value = current_value + 1
            self.progress_var.set(new_value)

            # Schedule the next update after a short delay
            self.master.after(100, self.update_progress)
        else:
            # If the script is not running, show the Back button
            self.show_back_button()

    def process_completed(self, event):
        # Unbind the event to avoid multiple calls
        self.master.unbind("<<ProcessCompleted>>")

        # Wait for the subprocess thread to complete
        self.master.thread.join()

        # Check if the script completed successfully or with an error
        if "ERROR" in self.master.process_output or "No" in self.master.process_output:
            # Handle the case where an error occurred
            self.handle_error()
        else:
            # Clean up: remove the temporary Bash script file
            if os.path.exists(self.bashscript_path):
                os.remove(self.bashscript_path)
                os.remove(self.awk_path)
            if self.test_var.get() == 1:
                self.run_test_report()
            # Update the progress bar to 100%
            self.progress_var.set(100)

            # Script has completed successfully
            print("Script completed!")

            # Add code to display the work completed screen
            self.coveragereport_complete_screen()

    def handle_error(self):
        # Handle the case where an error occurred during script execution
        print("Script encountered an error!")
        # Add code to convey the error message to the user
        error_label = tk.Label(self.second_screen_frame, text="Error occurred during script execution!", fg="red")
        error_label.pack(pady=20)
        # Show the Back button to allow the user to return to the file selector screen
        self.show_back_button()
        # Enable the Back button
        self.back_button['state'] = tk.NORMAL

    def testreport_complete_screen(self):
        # Hide the Get Coverage Report button
        self.generate_button.pack_forget()

        # Enable the Back button
        self.back_button['state'] = tk.NORMAL

        # Add code to display the work completed screen
        completed_label = tk.Label(self.second_screen_frame, text="Test Report Generated!")
        completed_label.pack(pady=20)

    def coveragereport_complete_screen(self):
        # Hide the Get Coverage Report button
        self.generate_button.pack_forget()

        # Enable the Back button
        self.back_button['state'] = tk.NORMAL

        # Add code to display the work completed screen
        completed_label = tk.Label(self.second_screen_frame, text="Coverage Report Generated!")
        completed_label.pack(pady=20)

    def show_back_button(self):
        # Hide the progress bar
        self.progress_bar.pack_forget()

        # Show the Back button
        self.back_button.pack()

    def show_progress_bar(self):
        # Show the progress bar
        self.progress_bar.pack()

    def show_file_selector_frame(self):
        # Hide the second screen frame
        self.second_screen_frame.place_forget()

        # Show the file selector frame
        self.file_selector_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Reset the application state
        self.reset_application()

    def reset_application(self):
        # Reset the application state to its initial values
        self.script_running = False

        # Clear the checkboxes
        self.coverage_var.set(0)
        self.test_var.set(0)

        # Reset the progress bar
        self.progress_var.set(0)

        # Hide the progress bar
        self.progress_bar.pack_forget()

# Create the main application window
root = tk.Tk()

# Set the size of the main application window
root.geometry("500x400")  # Adjust the width and height as needed

gtest_report_generator = GTestReportGenerator()

# Initialize the app
app = TextFileSelectorApp(root,gtest_report_generator)

# Run the application
root.mainloop()
