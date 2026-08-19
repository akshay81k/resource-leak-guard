package com.example;

import java.io.*;
import java.sql.*;
import java.util.List;

public class ReportExporter {

    public void exportUserReports(String dbUrl, List<String> userIds, String outputDir) throws SQLException {

        try (Connection conn = DriverManager.getConnection(dbUrl)) { // (1) fixed: auto-closed

            for (String userId : userIds) {

                if (userId != null && !userId.isEmpty()) {

                    try (
                        Statement stmt = conn.createStatement();           // (2) fixed: auto-closed
                        ResultSet rs = stmt.executeQuery(
                            "SELECT * FROM users WHERE id = '" + userId + "'"
                        );                                                  // (3) fixed: auto-closed
                        FileWriter writer = new FileWriter(outputDir + "/" + userId + ".csv") // (4) fixed: auto-closed
                    ) {
                        while (rs.next()) {
                            String name = rs.getString("username");
                            String email = rs.getString("email");

                            if (name == null) {
                                continue; // safe now — writer still gets closed by try-with-resources
                            }

                            writer.write(name + "," + email + "\n");
                        }

                    } catch (SQLException e) {
                        System.err.println("Query failed for user: " + userId);
                    } catch (IOException e) {
                        System.err.println("Write failed for user: " + userId);
                    }
                }
            }

        } // conn closed here automatically, even if an exception propagates out of the loop
    }
}