package com.example;

import java.io.*;
import java.sql.*;
import java.util.List;

public class ReportExporter {

    public void exportUserReports(String dbUrl, List<String> userIds, String outputDir) throws SQLException {
        Connection conn = DriverManager.getConnection(dbUrl); // (1) Leaked: never closed on any path

        for (String userId : userIds) {

            if (userId != null && !userId.isEmpty()) {

                Statement stmt = conn.createStatement(); // (2) Leaked: only closed inside the try, not on exception path
                try {
                    ResultSet rs = stmt.executeQuery(
                        "SELECT * FROM users WHERE id = '" + userId + "'"
                    ); // (3) Leaked: never closed at all, even on happy path

                    FileWriter writer = new FileWriter(outputDir + "/" + userId + ".csv"); // (4) Leaked: only closed if write succeeds

                    while (rs.next()) {
                        String name = rs.getString("username");
                        String email = rs.getString("email");

                        if (name == null) {
                            continue; // skips the writer.close() below on this path too
                        }

                        writer.write(name + "," + email + "\n");
                    }

                    writer.close(); // only reached if no exception AND no early 'continue' skipped it in a bad refactor

                    stmt.close(); // closes stmt, but NOT rs, and not on the exception path below

                } catch (SQLException e) {
                    System.err.println("Query failed for user: " + userId);
                    // no cleanup here — stmt/rs from the try block leak on this path
                } catch (IOException e) {
                    System.err.println("Write failed for user: " + userId);
                }
            }
        }

        // conn is still open here — function ends without ever closing it
    }
}