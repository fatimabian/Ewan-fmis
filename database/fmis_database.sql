-- FMIS MySQL bootstrap script
-- Safe to import in phpMyAdmin: it never deletes an existing FMIS database.
-- Django migrations create and update the application tables.
CREATE DATABASE IF NOT EXISTS `fmis`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `fmis`;

-- Optional restricted local account. Change the password before using outside local development.
-- CREATE USER IF NOT EXISTS 'fmis_user'@'localhost' IDENTIFIED BY 'change-this-password';
-- GRANT ALL PRIVILEGES ON `fmis`.* TO 'fmis_user'@'localhost';
-- FLUSH PRIVILEGES;
