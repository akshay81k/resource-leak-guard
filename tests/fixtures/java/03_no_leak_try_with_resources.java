import java.io.*;

public class NoLeakTryWithResources {
    public void safeMethod(String path) throws IOException {
        try (FileInputStream fis = new FileInputStream(path)) {
            int data = fis.read();
            System.out.println(data);
        }
    }
}
