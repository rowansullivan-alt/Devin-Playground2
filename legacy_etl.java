/*
 * legacy_etl.java
 *
 * Loads a CSV file of store sales and totals revenue by region.
 *
 * Expected CSV layout (first line is a header):
 *
 *   store_id,region,product,quantity,unit_price
 *   1001,North,Widget,3,4.50
 *
 * Usage: java LegacyEtl sales.csv
 */

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.text.DecimalFormat;
import java.util.Enumeration;
import java.util.Hashtable;
import java.util.Vector;

class LegacyEtl {

    public static final int COL_STORE_ID   = 0;
    public static final int COL_REGION     = 1;
    public static final int COL_PRODUCT    = 2;
    public static final int COL_QUANTITY   = 3;
    public static final int COL_UNIT_PRICE = 4;
    public static final int NUM_COLUMNS    = 5;

    public static void main(String[] args) {
        if (args.length < 1) {
            System.err.println("Usage: java LegacyEtl <sales.csv>");
            System.exit(1);
        }

        String fileName = args[0];
        Hashtable totals = new Hashtable();
        Vector regionOrder = new Vector();
        BufferedReader reader = null;
        int lineNumber = 0;
        int rowsLoaded = 0;
        int rowsSkipped = 0;

        try {
            reader = new BufferedReader(new FileReader(fileName));
            String line = reader.readLine();
            lineNumber++;

            while ((line = reader.readLine()) != null) {
                lineNumber++;
                if (line.trim().length() == 0) {
                    continue;
                }

                String[] fields = splitLine(line);
                if (fields == null) {
                    System.err.println("WARNING: line " + lineNumber
                            + " has wrong number of columns, skipped");
                    rowsSkipped++;
                    continue;
                }

                String region = fields[COL_REGION].trim();
                int quantity;
                double unitPrice;
                try {
                    quantity = Integer.parseInt(fields[COL_QUANTITY].trim());
                    unitPrice = Double.parseDouble(fields[COL_UNIT_PRICE].trim());
                } catch (NumberFormatException e) {
                    System.err.println("WARNING: line " + lineNumber
                            + " has bad number, skipped");
                    rowsSkipped++;
                    continue;
                }

                double revenue = quantity * unitPrice;
                Double current = (Double) totals.get(region);
                if (current == null) {
                    current = new Double(0.0);
                    regionOrder.addElement(region);
                }
                totals.put(region, new Double(current.doubleValue() + revenue));
                rowsLoaded++;
            }
        } catch (IOException e) {
            System.err.println("ERROR: could not read " + fileName + ": " + e.getMessage());
            System.exit(2);
        } finally {
            if (reader != null) {
                try {
                    reader.close();
                } catch (IOException e) {
                    // ignore
                }
            }
        }

        printReport(totals, regionOrder, rowsLoaded, rowsSkipped);
    }

    private static String[] splitLine(String line) {
        String[] fields = line.split(",", -1);
        if (fields.length != NUM_COLUMNS) {
            return null;
        }
        return fields;
    }

    private static void printReport(Hashtable totals, Vector regionOrder,
                                    int rowsLoaded, int rowsSkipped) {
        DecimalFormat money = new DecimalFormat("#,##0.00");
        double grandTotal = 0.0;

        System.out.println("REVENUE BY REGION");
        System.out.println("=================");
        Enumeration e = regionOrder.elements();
        while (e.hasMoreElements()) {
            String region = (String) e.nextElement();
            double amount = ((Double) totals.get(region)).doubleValue();
            grandTotal = grandTotal + amount;
            System.out.println(padRight(region, 20) + money.format(amount));
        }
        System.out.println("-----------------");
        System.out.println(padRight("TOTAL", 20) + money.format(grandTotal));
        System.out.println();
        System.out.println("Rows loaded:  " + rowsLoaded);
        System.out.println("Rows skipped: " + rowsSkipped);
    }

    private static String padRight(String s, int width) {
        StringBuffer sb = new StringBuffer(s);
        while (sb.length() < width) {
            sb.append(' ');
        }
        return sb.toString();
    }
}
