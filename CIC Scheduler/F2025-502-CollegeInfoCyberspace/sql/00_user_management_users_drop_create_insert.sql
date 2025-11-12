USE user_management;

DROP TABLE IF EXISTS CIC_CourseOffering;
DROP TABLE IF EXISTS CIC_FacultyPreference;
DROP TABLE IF EXISTS CIC_Program;
DROP TABLE IF EXISTS CIC_Semester;
DROP TABLE IF EXISTS CIC_Course;
DROP TABLE IF EXISTS CIC_FacultyProfile;
DROP TABLE IF EXISTS user_management.SystemUser;

CREATE TABLE SystemUser (
	userId INT AUTO_INCREMENT PRIMARY KEY,
    userName VARCHAR(255) NOT NULL,
    userEmail VARCHAR(255) NOT NULL UNIQUE,
    userPassword VARCHAR(255) NOT NULL,
    userRole ENUM('Admin', 'Customer') NOT NULL
); 

INSERT INTO SystemUser (userName, userEmail, userPassword, userRole) VALUES
('Admin1', 'admin1@ndu.edu', '123456',  'Admin'),
('Admin2', 'admin2@ndu.edu', '123456',  'Admin'),
('FAC-001', 'faculty1@ndu.edu', '123456', 'Customer'),
('FAC-002', 'faculty2@ndu.edu', '123456', 'Customer'),
('FAC-003', 'faculty3@ndu.edu', '123456', 'Customer'),
('FAC-004', 'faculty4@ndu.edu', '123456', 'Customer'),
('FAC-005', 'faculty5@ndu.edu', '123456', 'Customer'),
('FAC-006', 'faculty6@ndu.edu', '123456', 'Customer'),
('FAC-007', 'faculty7@ndu.edu', '123456', 'Customer'),
('FAC-008', 'faculty8@ndu.edu', '123456', 'Customer'),
('FAC-009', 'faculty9@ndu.edu', '123456', 'Customer'),
('FAC-010', 'faculty10@ndu.edu', '123456', 'Customer'),
('FAC-011', 'faculty11@ndu.edu', '123456', 'Customer'),
('FAC-012', 'faculty12@ndu.edu', '123456', 'Customer'),
('FAC-013', 'faculty13@ndu.edu', '123456', 'Customer'),
('FAC-014', 'faculty14@ndu.edu', '123456', 'Customer'),
('FAC-015', 'faculty15@ndu.edu', '123456', 'Customer'),
('FAC-016', 'faculty16@ndu.edu', '123456', 'Customer'),
('FAC-017', 'faculty17@ndu.edu', '123456', 'Customer'),
('FAC-018', 'faculty18@ndu.edu', '123456', 'Customer'),
('FAC-019', 'faculty19@ndu.edu', '123456', 'Customer'),
('FAC-020', 'faculty20@ndu.edu', '123456', 'Customer'),
('FAC-021', 'faculty21@ndu.edu', '123456', 'Customer'),
('FAC-022', 'faculty22@ndu.edu', '123456', 'Customer'),
('FAC-023', 'faculty23@ndu.edu', '123456', 'Customer'),
('FAC-024', 'faculty24@ndu.edu', '123456', 'Customer'),
('FAC-025', 'faculty25@ndu.edu', '123456', 'Customer');

SELECT * FROM user_management.SystemUser;
