USE user_management;

-- Drop tables
DROP TABLE IF EXISTS CIC_Output;
DROP TABLE IF EXISTS CIC_CourseOffering;
DROP TABLE IF EXISTS CIC_FacultyPreference;
DROP TABLE IF EXISTS CIC_Program;
DROP TABLE IF EXISTS CIC_Semester;
DROP TABLE IF EXISTS CIC_Course;
DROP TABLE IF EXISTS CIC_FacultyProfile;

-- Create tables
CREATE TABLE CIC_FacultyProfile (
    facultyUserId INT NOT NULL,
    facultyName VARCHAR(255) NOT NULL,
    facultyExperience VARCHAR(50),
    CONSTRAINT pk_FacultyProfile_facultyUserId PRIMARY KEY (facultyUserId),
    CONSTRAINT fk_FacultyProfile_facultyUserId FOREIGN KEY (facultyUserId)
        REFERENCES SystemUser (userId)
        ON DELETE CASCADE ON UPDATE CASCADE);

CREATE TABLE CIC_Course (
    courseId                  CHAR(8)       NOT NULL,
    courseTitle               VARCHAR(200)  NOT NULL,
    courseCategory            VARCHAR(50),
    courseCredits             INT,
    courseBackgroundRequired  VARCHAR(100),
    CONSTRAINT pk_Course_courseId PRIMARY KEY (courseId)
);

CREATE TABLE CIC_Semester (
    semesterId              CHAR(7)     NOT NULL,
    semesterTerm            VARCHAR(10) ,
    semesterYear            INT ,
    semesterStartDate       DATE,
    semesterEndDate         DATE,
    semesterIsActive        CHAR(1),
    CONSTRAINT pk_Semester_semesterId PRIMARY KEY (semesterId),
    CONSTRAINT ck_Semester_semesterYear CHECK (semesterYear >= 2000),
    CONSTRAINT ck_Semester_dates CHECK (semesterStartDate IS NULL OR semesterEndDate IS NULL OR semesterEndDate >= semesterStartDate)
);

CREATE TABLE CIC_Program (
    programId           VARCHAR(20) NOT NULL,
    programName         VARCHAR(60),
    programType         VARCHAR(40),
    coreCreditRequest   INT,
    NDUElective         INT,
    CICElective         INT,
    programAwarded      VARCHAR(50),
    CONSTRAINT pk_Program_programId PRIMARY KEY (programId)
);


CREATE TABLE CIC_FacultyPreference (
    facultyUserId  INT NOT NULL,
    semesterId     CHAR(7) NOT NULL,
    priorityRank   INT NOT NULL,
    courseId       CHAR(8) NOT NULL,
    CONSTRAINT pk_FacultyPreference_facultyUserId_semesterId_priorityRank PRIMARY KEY (facultyUserId, semesterId, priorityRank),

    CONSTRAINT fk_FacultyPreference_facultyUserId FOREIGN KEY (facultyUserId)
        REFERENCES CIC_FacultyProfile (facultyUserId)
        ON DELETE CASCADE ON UPDATE CASCADE,
    
    CONSTRAINT fk_FacultyPreference_courseId FOREIGN KEY (courseId)
        REFERENCES CIC_Course (courseId)
        ON DELETE NO ACTION ON UPDATE CASCADE,
    
    CONSTRAINT fk_FacultyPreference_semesterId FOREIGN KEY (semesterId)
        REFERENCES CIC_Semester (semesterId)
        ON DELETE NO ACTION ON UPDATE CASCADE
);

CREATE TABLE CIC_CourseOffering (
    offeringId       CHAR(10)     NOT NULL,
    courseId         CHAR(8)      NOT NULL,
    semesterId       CHAR(10)     NOT NULL,
    sectionQuantity  INT,
    CONSTRAINT pk_CourseOffering_offeringId PRIMARY KEY (offeringId),
    
    CONSTRAINT fk_CourseOffering_courseId FOREIGN KEY (courseId)
        REFERENCES CIC_Course (courseId)
        ON DELETE CASCADE ON UPDATE CASCADE,
    
    CONSTRAINT fk_CourseOffering_semesterId FOREIGN KEY (semesterId)
        REFERENCES CIC_Semester (semesterId)
        ON DELETE CASCADE ON UPDATE CASCADE
);


CREATE TABLE CIC_Output (
    outputId                INT AUTO_INCREMENT NOT NULL,
    semesterId              CHAR(7)       NOT NULL,
    offeringId              CHAR(10)      NOT NULL,
    courseId                CHAR(8)       NOT NULL,
    courseTitle             VARCHAR(200)  NOT NULL,
    section                 CHAR(2)       NOT NULL,
    assignedFacultyUserId   INT,
    facultyName             VARCHAR(255),
    CONSTRAINT pk_Output_outputId PRIMARY KEY (outputId),
    
    CONSTRAINT fk_Output_semesterId FOREIGN KEY (semesterId)
        REFERENCES CIC_Semester (semesterId)
        ON DELETE CASCADE ON UPDATE CASCADE,
    
    CONSTRAINT fk_Output_offeringId FOREIGN KEY (offeringId)
        REFERENCES CIC_CourseOffering (offeringId)
        ON DELETE CASCADE ON UPDATE CASCADE,
    
    CONSTRAINT fk_Output_courseId FOREIGN KEY (courseId)
        REFERENCES CIC_Course (courseId)
        ON DELETE CASCADE ON UPDATE CASCADE,

    CONSTRAINT fk_Output_assignedFacultyUserId FOREIGN KEY (assignedFacultyUserId)
        REFERENCES CIC_FacultyProfile (facultyUserId)
        ON DELETE CASCADE ON UPDATE CASCADE
);