import java.io.*;

public class NoLeakFinallyBlock {
    public void safeMethod(String path) throws Exception {
        FileInputStream fis = new FileInputStream(path);
        try {
            int data = fis.read();
            System.out.println(data);
        } finally {
            fis.close();
        }
    }
}
