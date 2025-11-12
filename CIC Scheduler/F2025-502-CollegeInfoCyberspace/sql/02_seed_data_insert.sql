USE user_management;

-- Insert data
INSERT INTO CIC_FacultyProfile (facultyUserId, facultyName) VALUES
(3, 'FAC-001'),
(4, 'FAC-002'),
(5, 'FAC-003'),
(6, 'FAC-004'),
(7, 'FAC-005'),
(8, 'FAC-006'),
(9, 'FAC-007'),
(10, 'FAC-008'),
(11, 'FAC-009'),
(12, 'FAC-010'),
(13, 'FAC-011'),
(14, 'FAC-012'),
(15, 'FAC-013'),
(16, 'FAC-014'),
(17, 'FAC-015'),
(18, 'FAC-016'),
(19, 'FAC-017'),
(20, 'FAC-018'),
(21, 'FAC-019'),
(22, 'FAC-020'),
(23, 'FAC-021'),
(24, 'FAC-022'),
(25, 'FAC-023'),
(26, 'FAC-024'),
(27, 'FAC-025');

INSERT INTO CIC_Program (programId, programName, programType, coreCreditRequest, NDUElective, CICElective, programAwarded) VALUES
('CDO-CERT', 'Chief Data Officer', 'Certificates', 15, 0, 0, 'Graduate Certificate'),
('CIO-CERT', 'Chief Information Officer', 'Certificates', 15, 0, 0, 'Graduate Certificate'),
('CFO-CERT', 'Chief Financial Officer', 'Certificates', 15, 0, 0, 'Graduate Certificate'),
('CYBER-L-CERT', 'Cyber Leadership', 'Certificates', 15, 0, 0, 'Graduate Certificate'),
('CISO-CERT', 'Chief Information Security Officer', 'Certificates', 15, 0, 0, 'Graduate Certificate'),
('CIO-LDP', 'Chief Information Officer Leadership Development Program', 'Leadership Development Program', 15, 0, 0, 'Graduate Certificate'),
('CYBER-LDP', 'Cyber Leadership Development Program', 'Leadership Development Program', 15, 0, 0, 'Graduate Certificate'),
('SICS-PT', 'Strategic Information and Cyberspace Studies', 'Part-Time Degree', 27, 0, 9, 'Master of Science Degree'),
('SICS-JMPE', 'Strategic Information and Cyberspace Studies', 'Joint Professional Military Education', 27, 6, 0, 'Master of Science Degree');

INSERT INTO CIC_Semester (semesterId, semesterTerm, semesterYear, semesterStartDate, semesterEndDate, semesterIsActive) VALUES
('2025-03', 'Fall', 2025, '2025-08-04', '2025-12-15', 'T'),
('2026-01', 'Spring', 2026, '2026-01-01', '2026-03-31', 'F'),
('2026-02', 'Summer', 2026, '2026-04-01', '2026-07-31', 'F'),
('2026-03', 'Fall', 2026, '2026-08-04', '2026-12-15', 'F'),
('2027-01', 'Spring', 2027, '2027-01-01', '2027-03-31', 'F'),
('2027-02', 'Summer', 2027, '2027-04-01', '2027-07-31', 'F'),
('2027-03', 'Fall', 2027, '2027-09-01', '2027-12-15', 'F');

INSERT INTO CIC_Course (courseId, courseTitle, courseCategory, courseCredits, courseBackgroundRequired) VALUES
('CIC6164', 'Strategic Thinking and Communications', 'Core', 3, NULL),
('CIC6170', 'Practicum, Experiantial Learning, and Capstone', 'Core',  3, NULL),
('CIC6173', 'Strategic Art for the Cyber and Information Enviornment ', 'Core',  3, NULL),
('CIC6174', 'Governance, Authorities, and Ethics ', 'Core',  3, NULL),
('CIC6175', 'Cyber Strategy and Conflict', 'Core',  3, NULL),
('CIC6176', 'Information Warfare Strategy ', 'Core',  3, NULL),
('CIC6177', 'Cyber Power and Technology Strategy', 'Core',  3, NULL),
('CIC6178', 'Diplomacy, Information and Cyber in the Global Environment', 'Core',  3, NULL),
('CIC6179', 'Cyber and Information Effects in Military Operations', 'Core',  3, NULL),
('CIC6201', 'Cybersecurity for Strategic Leaders ', 'Core',  3, NULL),
('CIC6211', 'Cybersecurity  Fundamentals', 'Core',  3, NULL),
('CIC6217', 'Illicit Use of Cyber ', 'Core',  3, NULL),
('CIC6218', 'Risk Management Framework for Strategic Leaders ', 'Core',  3, NULL),
('CIC6219', 'Cyber Essentials for Senior Leaders', 'Core',  3, NULL),
('CIC6220', 'Engaging Partners and Adversaries through Diplomacy', 'Core',  3, NULL),
('CIC6221', 'Cyberspace Activities and Authorities', 'Core',  3, NULL),
('CIC6303', 'CIO 2.0 ', 'Core',  3, NULL),
('CIC6328', 'Strategic Performance and Budget Management', 'Core',  3, NULL),
('CIC6330', 'National Security and Cyber Strategies', 'Core',  3, NULL),
('CIC6414', 'Data Management Strategies and Technologies', 'Core',  3, NULL),
('CIC6415', 'Strategic Information Technology Acquisition', 'Core',  3, NULL),
('CIC6419', 'Data Strategy and Governance', 'Core',  3, NULL),
('CIC6420', 'Data Analytics for Leaders', 'Core',  3, NULL),
('CIC6442', 'Artificial Intelligence for Data Leaders', 'Core',  3, NULL),
('CIC6443', 'Emerging and Disruptive Technologies', 'Core',  3, NULL),
('CIC6504', 'Continuity of Operations ', 'Core',  3, NULL),
('CIC6512', 'Multi Agency Information Enabled Collaboration ', 'Core',  3, NULL),
('CIC6606', 'White House, Congress and the Budget', 'Core',  3, NULL),
('CIC6607', 'The Future of Federal Financial Information Sharing', 'Core',  3, NULL),
('CIC6608', 'Risk Management, Internal Controls and Auditing for Leaders', 'Core',  3, NULL);

INSERT INTO CIC_CourseOffering (offeringId, courseId, semesterId, sectionQuantity) VALUES
('OFF-000001', 'CIC6164', '2026-01', 5),
('OFF-000002', 'CIC6170', '2026-01', 4),
('OFF-000003', 'CIC6173', '2026-01', 7),
('OFF-000004', 'CIC6174', '2026-01', 6),
('OFF-000005', 'CIC6175', '2026-01', 6),
('OFF-000006', 'CIC6176', '2026-01', 6),
('OFF-000007', 'CIC6177', '2026-01', 5),
('OFF-000008', 'CIC6178', '2026-01', 5),
('OFF-000009', 'CIC6179', '2026-01', 4),
('OFF-000010', 'CIC6201', '2026-01', 2),
('OFF-000011', 'CIC6211', '2026-01', 3),
('OFF-000012', 'CIC6217', '2026-01', 1),
('OFF-000013', 'CIC6218', '2026-01', 2),
('OFF-000014', 'CIC6219', '2026-01', 2),
('OFF-000015', 'CIC6220', '2026-01', 3),
('OFF-000016', 'CIC6221', '2026-01', 1),
('OFF-000017', 'CIC6303', '2026-01', 2),
('OFF-000018', 'CIC6328', '2026-01', 2),
('OFF-000019', 'CIC6330', '2026-01', 2),
('OFF-000020', 'CIC6414', '2026-01', 2),
('OFF-000021', 'CIC6415', '2026-01', 2),
('OFF-000022', 'CIC6419', '2026-01', 1),
('OFF-000023', 'CIC6420', '2026-01', 1),
('OFF-000024', 'CIC6442', '2026-01', 1),
('OFF-000025', 'CIC6443', '2026-01', 4),
('OFF-000026', 'CIC6504', '2026-01', 1),
('OFF-000027', 'CIC6512', '2026-01', 2),
('OFF-000028', 'CIC6606', '2026-01', 1),
('OFF-000029', 'CIC6607', '2026-01', 1),
('OFF-000030', 'CIC6608', '2026-01', 1);


-- Query
SELECT * FROM SystemUser;
SELECT * FROM CIC_FacultyProfile;
SELECT * FROM CIC_Program;
SELECT * FROM CIC_Semester;
SELECT * FROM CIC_Course;
SELECT * FROM CIC_CourseOffering;