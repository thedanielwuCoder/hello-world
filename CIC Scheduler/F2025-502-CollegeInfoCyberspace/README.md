CIC Course Schedule Overview

System Overview
This project is an AI-powered course scheduling system that automates matching instructor preferences to administrative course demands.

Inputs
Professor Preferences: Instructors submit their preferred courses and availability.
Demand: Determined by the administrator (Dr. Chen).

Algorithm Function
The AI algorithm processes both instructor preferences and administrative demand, generating four (4) optimized schedule outputs for review.

Instructor Interface
Preferences Submission
Course Selection: Dropdown menu listing available courses
Preference Level: Numeric scale from 1 to 5, where
1 = Most Preferred
5 = Least Preferred
Course Display: Each option shows both Course Name and Course ID together
Once submitted, all instructor preferences are stored for administrative review.


Administrator Workflow (Dr. Chen)
Step 1 – Collect Preferences
Admin receives all submitted preferences from 25 instructors.
The system validates completeness.
If any instructor has not submitted, the system notifies the admin.

Step 2 – Generate AI Schedules
Admin clicks “Run AI Algorithm”.
The algorithm produces 4 different schedule outputs, each displayed in a separate table view.
Each table represents one optimized mapping between professors and courses.

Step 3 – Analyze & Decide
Admin can click “Run AI Report” to generate a summary report showing:
Pros & Cons
for each of the four outputs.

Step 4 – Edit & Publish
If none of the generated schedules are satisfactory, the admin may:
Use the Edit button to manually adjust the mappings.
Once finalized, Publish the selected or edited schedule.

For now, this page displays only the courses each instructor will be teaching, based on the finalized schedule approved by the admin.

Future Enhancements
Integrate AI report generation and editing features
Enable version tracking for published schedules
Add automatic email notifications for incomplete submissions
